import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voxlab import synthetic_stress as ss


ROOT = Path(__file__).resolve().parents[1]


def gold_row(pair_id, relation, stance_b="FAVOR", prop_b="Prop B"):
    return {"pair_id": pair_id, "derived_relation": relation, "stance_a": "FAVOR", "stance_b": stance_b,
            "target_proposition_a": "Prop A", "target_proposition_b": prop_b, "gold_round": "pilot"}


def response(text):
    return {"choices": [{"message": {"content": text}}]}


class PlanTests(unittest.TestCase):

    def test_operations_follow_source_relation(self):
        plan = ss.build_plan([gold_row("m1", "STANCE_MAINTAINED"), gold_row("i1", "INCOMPARABLE"),
                              gold_row("u1", "RELATION_UNCERTAIN")])
        ops = sorted((s["source_pair_id"], s["operation"]) for s in plan)
        self.assertEqual(ops, [("i1", "REVERSE_ON_INCOMPARABLE"), ("m1", "NEGATED_PARAPHRASE"),
                               ("m1", "REVERSE_ON_COMPARABLE"), ("m1", "SHIFT_PROPOSITION")])
        self.assertTrue(all(s["label_source"] == "SYNTHETIC_EXPECTED" for s in plan))

    def test_expected_labels(self):
        plan = {s["operation"]: s for s in ss.build_plan([gold_row("m1", "STANCE_MAINTAINED", "AGAINST")])}
        self.assertEqual(plan["REVERSE_ON_COMPARABLE"]["expected_relation"], "STANCE_REVERSED")
        self.assertEqual(plan["REVERSE_ON_COMPARABLE"]["expected_verifier_stance"], "FAVOR")
        self.assertEqual(plan["NEGATED_PARAPHRASE"]["expected_relation"], "STANCE_MAINTAINED")
        self.assertEqual(plan["NEGATED_PARAPHRASE"]["expected_verifier_stance"], "AGAINST")
        self.assertEqual(plan["SHIFT_PROPOSITION"]["expected_relation"], "INCOMPARABLE")
        self.assertEqual(plan["SHIFT_PROPOSITION"]["expected_verifier_stance"], "NOT_ADDRESSED")

    def test_side_without_determinate_stance_is_skipped(self):
        self.assertEqual(ss.build_plan([gold_row("i1", "INCOMPARABLE", stance_b="")]), [])
        self.assertEqual(ss.build_plan([gold_row("i1", "INCOMPARABLE", prop_b=" ")]), [])

    def test_spec_ids_are_stable_and_distinct(self):
        self.assertEqual(ss.spec_id("p", "NEGATED_PARAPHRASE"), ss.spec_id("p", "NEGATED_PARAPHRASE"))
        self.assertNotEqual(ss.spec_id("p", "NEGATED_PARAPHRASE"), ss.spec_id("p", "SHIFT_PROPOSITION"))

    def test_real_gold_plan_counts(self):
        plan = ss.build_plan(ss.load_gold(ROOT))
        counts = {}
        for spec in plan:
            counts[spec["operation"]] = counts.get(spec["operation"], 0) + 1
        self.assertEqual(counts, {"REVERSE_ON_COMPARABLE": 12, "NEGATED_PARAPHRASE": 12,
                                  "SHIFT_PROPOSITION": 12, "REVERSE_ON_INCOMPARABLE": 31})


class GenerationParsingTests(unittest.TestCase):

    def test_well_formed(self):
        raw = "PROPOSICAO_RESULTANTE: X deve acabar\nPOSICAO_RESULTANTE: against\n===TEXTO===\nLinha 1\nLinha 2\n===FIM==="
        parsed = ss.parse_generation(raw)
        self.assertTrue(parsed["generation_parsed"])
        self.assertEqual(parsed["resulting_stance"], "AGAINST")
        self.assertEqual(parsed["rewritten_text"], "Linha 1\nLinha 2")

    def test_missing_end_marker_is_unparsed(self):
        parsed = ss.parse_generation("PROPOSICAO_RESULTANTE: X\nPOSICAO_RESULTANTE: FAVOR\n===TEXTO===\nabc")
        self.assertFalse(parsed["generation_parsed"])
        self.assertEqual(parsed["rewritten_text"], "")


class DeterministicCheckTests(unittest.TestCase):
    ORIGINAL = " ".join(f"palavra{i}" for i in range(200))

    def test_small_local_edit_passes(self):
        rewritten = self.ORIGINAL.replace("palavra50 palavra51", "não palavra51")
        self.assertTrue(ss.deterministic_checks(self.ORIGINAL, rewritten)["deterministic_ok"])

    def test_identical_text_fails(self):
        checks = ss.deterministic_checks(self.ORIGINAL, self.ORIGINAL)
        self.assertIn("NOTHING_CHANGED", checks["deterministic_failures"])

    def test_full_rewrite_fails(self):
        checks = ss.deterministic_checks(self.ORIGINAL, " ".join(f"outra{i}" for i in range(200)))
        self.assertIn("TOO_MUCH_REWRITTEN", checks["deterministic_failures"])

    def test_edit_markers_fail(self):
        checks = ss.deterministic_checks(self.ORIGINAL, self.ORIGINAL + " [reescrito]")
        self.assertIn("EDIT_MARKERS", checks["deterministic_failures"])

    def test_empty_fails(self):
        self.assertFalse(ss.deterministic_checks(self.ORIGINAL, "  ")["deterministic_ok"])


class CopyNoiseTests(unittest.TestCase):

    def test_typo_is_noise_but_rewrite_is_not(self):
        original = "Primeiro parágrafo com bastante texto para comparar direito.\nSegundo parágrafo que muda."
        typo = original.replace("bastante", "bastnte")
        self.assertEqual(ss.copy_noise_paragraphs(original, typo), 1)
        rewrite = original.replace("Segundo parágrafo que muda.", "Outro conteúdo totalmente diferente aqui.")
        self.assertEqual(ss.copy_noise_paragraphs(original, rewrite), 0)


class VerificationTests(unittest.TestCase):
    SPEC = {"expected_verifier_stance": "AGAINST"}
    GEN = {"generation_parsed": True}
    CHECKS = {"deterministic_ok": True, "deterministic_failures": ""}

    def verification(self, **overrides):
        payload = {"operation_achieved": "YES", "other_content_preserved": "YES", "internally_consistent": "YES",
                   "natural": "YES", "rewritten_stance_on_original_target": "AGAINST", "reasoning": "ok"}
        payload.update(overrides)
        return ss.parse_verification(json.dumps(payload))

    def test_all_yes_and_expected_stance_is_accepted(self):
        accepted, reasons = ss.accept(self.SPEC, self.GEN, self.CHECKS, self.verification())
        self.assertTrue(accepted, reasons)

    def test_any_non_yes_rejects(self):
        accepted, reasons = ss.accept(self.SPEC, self.GEN, self.CHECKS, self.verification(natural="UNCERTAIN"))
        self.assertFalse(accepted)
        self.assertIn("VERIFIER_NATURAL_UNCERTAIN", reasons)

    def test_stance_mismatch_rejects(self):
        accepted, reasons = ss.accept(self.SPEC, self.GEN, self.CHECKS,
                                      self.verification(rewritten_stance_on_original_target="FAVOR"))
        self.assertFalse(accepted)
        self.assertIn("VERIFIER_STANCE_MISMATCH", reasons)

    def test_out_of_vocabulary_is_malformed(self):
        parsed = self.verification(operation_achieved="SIM")
        self.assertTrue(parsed["verification_malformed"])
        self.assertFalse(ss.accept(self.SPEC, self.GEN, self.CHECKS, parsed)[0])

    def test_failed_deterministic_check_rejects(self):
        accepted, reasons = ss.accept(self.SPEC, self.GEN, {"deterministic_ok": False,
                                                            "deterministic_failures": "NOTHING_CHANGED"},
                                      self.verification())
        self.assertFalse(accepted)
        self.assertIn("DETERMINISTIC:NOTHING_CHANGED", reasons)


class PerturbedPairTests(unittest.TestCase):

    def test_only_display_fields_and_side_b_replaced(self):
        row = {field: f"orig_{field}" for field in ss.DISPLAY_FIELDS}
        row.update({"stance_a": "FAVOR", "same_proposition": "YES", "derived_relation": "STANCE_MAINTAINED"})
        pair = ss.perturbed_pair(row, {"spec_id": "syn_x"}, "novo texto")
        self.assertEqual(set(pair), set(ss.DISPLAY_FIELDS))
        self.assertEqual(pair["pair_id"], "syn_x")
        self.assertEqual(pair["text_b"], "novo texto")
        self.assertEqual(pair["text_a"], "orig_text_a")
        self.assertEqual(pair["evidence_b"], "")


class MetricsTests(unittest.TestCase):

    def test_wilson_bounds(self):
        self.assertIsNone(ss.wilson(0, 0))
        low, high = ss.wilson(0, 12)
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.2425, places=3)

    def test_headline_rates(self):
        rows = []
        for pred_c in ("STANCE_REVERSED", "STANCE_REVERSED", "INCOMPARABLE"):
            rows.append({"model": "m", "operation": "REVERSE_ON_COMPARABLE", "expected_relation": "STANCE_REVERSED",
                         "A_end_to_end": "STANCE_MAINTAINED", "B_forced_comparability": "STANCE_REVERSED",
                         "C_structured_with_gate": pred_c})
        rows.append({"model": "m", "operation": "REVERSE_ON_INCOMPARABLE", "expected_relation": "INCOMPARABLE",
                     "A_end_to_end": "INCOMPARABLE", "B_forced_comparability": "STANCE_REVERSED",
                     "C_structured_with_gate": "INCOMPARABLE"})
        head = ss.headline(ss.summarize(rows))["m"]
        self.assertEqual(head["C_structured_with_gate"]["reversal_recall__REVERSE_ON_COMPARABLE"]["k"], 2)
        self.assertEqual(head["A_end_to_end"]["reversal_recall__REVERSE_ON_COMPARABLE"]["k"], 0)
        self.assertEqual(head["B_forced_comparability"]["false_reversal__REVERSE_ON_INCOMPARABLE"]["rate"], 1.0)
        self.assertEqual(head["C_structured_with_gate"]["false_reversal__REVERSE_ON_INCOMPARABLE"]["rate"], 0.0)


class NetworkSafetyTests(unittest.TestCase):

    def test_dry_run_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(ss, "OUT_DIR", Path(tmp)), \
                mock.patch("voxlab.synthetic_stress.chat_completion") as call:
            result = ss.run(ROOT, execute=False)
        call.assert_not_called()
        self.assertEqual(result["mode"], "DRY_RUN_NO_REQUESTS_SENT")
        self.assertGreater(result["total_calls_upper_bound"], 0)

    def test_cached_call_reuses_disk_and_skips_without_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("voxlab.synthetic_stress.chat_completion") as call:
                self.assertIsNone(ss.cached_call(root, "generate", "m/x", "k", "prompt", execute=False))
                call.assert_not_called()
                call.return_value = response("ok")
                first = ss.cached_call(root, "generate", "m/x", "k", "prompt", execute=True)
                second = ss.cached_call(root, "generate", "m/x", "k", "prompt", execute=True)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(first, second)


class EndToEndMockTests(unittest.TestCase):
    """Full executed run on a tiny synthetic gold with every API call mocked."""

    def test_pipeline_with_mocked_models(self):
        original_b = " ".join(f"w{i}" for i in range(100))
        gold = [{field: "" for field in ss.DISPLAY_FIELDS} | {
            "pair_id": "m1", "derived_relation": "STANCE_MAINTAINED", "stance_a": "FAVOR", "stance_b": "FAVOR",
            "target_proposition_a": "A", "target_proposition_b": "B", "gold_round": "pilot",
            "text_a": "texto a", "text_b": original_b}]
        rewritten = original_b.replace("w10 w11", "não w11")

        def fake_chat(root, model, messages, **kwargs):
            prompt = messages[0]["content"]
            if model == ss.GENERATOR_MODEL:
                return response(f"PROPOSICAO_RESULTANTE: B\nPOSICAO_RESULTANTE: AGAINST\n===TEXTO===\n{rewritten}\n===FIM===")
            if model == ss.VERIFIER_MODEL:
                expected = "AGAINST" if "Inverta" in prompt else ("NOT_ADDRESSED" if "DIFERENTE" in prompt else "FAVOR")
                return response(json.dumps({"operation_achieved": "YES", "other_content_preserved": "YES",
                                            "internally_consistent": "YES", "natural": "YES",
                                            "rewritten_stance_on_original_target": expected}))
            if '"relation"' in prompt:
                return response(json.dumps({"relation": "INCOMPARABLE", "reasoning": ""}))
            return response(json.dumps({"stance_determinable_a": "YES", "stance_determinable_b": "YES",
                                        "target_proposition_a": "A", "target_proposition_b": "B",
                                        "same_proposition": "YES", "stance_a": "FAVOR", "stance_b": "AGAINST"}))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prompts").mkdir()
            for path in (ss.GENERATE_PROMPT_PATH, ss.VERIFY_PROMPT_PATH, ss.END_TO_END_PROMPT_PATH,
                         ss.STRUCTURED_PROMPT_PATH):
                (root / path).write_text((ROOT / path).read_text(encoding="utf-8"), encoding="utf-8")
            with mock.patch.object(ss, "load_gold", return_value=gold), \
                    mock.patch.object(ss, "manifest", return_value={}), \
                    mock.patch("voxlab.synthetic_stress.chat_completion", side_effect=fake_chat):
                result = ss.run(root, execute=True)
        self.assertEqual(result["funnel"]["REVERSE_ON_COMPARABLE"], {"planned": 1, "accepted": 1})
        head = result["headline"]
        for model in ss.EVALUATED_MODELS:
            self.assertEqual(head[model]["C_structured_with_gate"]["reversal_recall__REVERSE_ON_COMPARABLE"]["k"], 1)
            self.assertEqual(head[model]["A_end_to_end"]["reversal_recall__REVERSE_ON_COMPARABLE"]["k"], 0)


if __name__ == "__main__":
    unittest.main()
