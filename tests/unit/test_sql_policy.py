from __future__ import annotations

import unittest

from insightforge.sandbox.executor import SQLSafetyError, validate_read_only_sql


class SQLPolicyTest(unittest.TestCase):
    def test_allows_single_read_only_query(self) -> None:
        self.assertEqual(validate_read_only_sql("SELECT COUNT(*) FROM dataset;"), "SELECT COUNT(*) FROM dataset")

    def test_blocks_mutation_and_file_access(self) -> None:
        for query in (
            "DELETE FROM dataset",
            "SELECT * FROM read_csv_auto('secret.csv')",
            "SELECT 1; SELECT 2",
        ):
            with self.subTest(query=query), self.assertRaises(SQLSafetyError):
                validate_read_only_sql(query)


if __name__ == "__main__":
    unittest.main()
