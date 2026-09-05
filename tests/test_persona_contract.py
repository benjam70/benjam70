import unittest

from payment_forensics import compile_all, compile_persona, load_persona_contract, persona_hash


class PersonaContractTests(unittest.TestCase):
    def test_all_hosts_compile_from_one_contract(self):
        compiled = compile_all()
        self.assertEqual(set(compiled), {"codex", "claude", "cursor", "grok"})
        for text in compiled.values():
            self.assertIn("Dudley", text)
            self.assertIn(persona_hash(), text)

    def test_contract_has_stable_identity_and_version(self):
        contract = load_persona_contract()
        self.assertEqual(contract["name"], "Dudley")
        self.assertTrue(contract["version"])
        self.assertEqual(len(persona_hash()), 64)

    def test_host_compilation_changes_adapter_header_not_identity(self):
        self.assertNotEqual(compile_persona("codex").splitlines()[0], compile_persona("grok").splitlines()[0])
        self.assertEqual(compile_persona("codex").split('"identity":')[1].splitlines()[0], compile_persona("grok").split('"identity":')[1].splitlines()[0])


if __name__ == "__main__":
    unittest.main()
