import unittest
try:
    from fastapi.testclient import TestClient
    from core.main import app
    HAS_TESTCLIENT = True
except Exception:
    HAS_TESTCLIENT = False

from core.services import (
    walk_json_path,
    is_partial,
    is_empty,
    discover_paths,
    path_to_dot_notation,
    extract_keys_from_json,
    compute_path_values_comparison,
    ParserAnalyticsService
)

class TestParserPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HAS_TESTCLIENT:
            cls.client = TestClient(app)
        else:
            cls.client = None

    @unittest.skipUnless(HAS_TESTCLIENT, "TestClient requires httpx")
    def test_root_serves_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Parser Validation", response.text)

    def test_index_html_has_path_values_modal(self):
        with open("core/static/index.html", "r") as f:
            html = f.read()
        self.assertIn("pathValuesModal", html)
        self.assertIn("btnViewPathValues", html)
        self.assertIn("kpiValTotalV1", html)

    def test_walk_json_path_nested_wildcard(self):
        data = {
            "details": {
                "locations": [
                    {"text": "Atlanta, GA"},
                    {"text": "Suwanee, GA"}
                ]
            }
        }
        extracted = walk_json_path(data, "root['details']['locations'][*]['text']")
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0][1], "Atlanta, GA")
        self.assertEqual(extracted[1][1], "Suwanee, GA")

    def test_is_partial(self):
        self.assertTrue(is_partial("lithia springs", "lithia springs, ga"))
        self.assertFalse(is_partial("Atlanta", "Atlanta"))
        self.assertFalse(is_partial("Python", "Java"))

    def test_is_empty(self):
        self.assertTrue(is_empty(""))
        self.assertTrue(is_empty([]))
        self.assertTrue(is_empty(None))
        self.assertTrue(is_empty({}))
        self.assertFalse(is_empty("value"))

    def test_discover_paths(self):
        data = {
            "details": {
                "locations": [{"text": "City"}],
                "skills": [{"name": "Python"}]
            }
        }
        paths = discover_paths(data)
        self.assertIn("root['details']['locations'][*]['text']", paths)
        self.assertIn("root['details']['skills'][*]['name']", paths)

    def test_path_to_dot_notation(self):
        self.assertEqual(
            path_to_dot_notation("root['details']['locations'][*]['text']"),
            "details.locations[*].text"
        )
        self.assertEqual(path_to_dot_notation("root['title']"), "title")
        self.assertEqual(path_to_dot_notation("root"), "")

    def test_extract_keys_from_json(self):
        sample = {
            "title": "Engineer",
            "skills": [
                {"name": "Python", "level": "Senior"},
                {"name": "FastAPI"}
            ]
        }
        occurrences, unique_paths, raw_keys = extract_keys_from_json(sample)
        self.assertIn("root['title']", unique_paths)
        self.assertIn("root['skills']", unique_paths)
        self.assertIn("root['skills'][*]['name']", unique_paths)
        self.assertIn("root['skills'][*]['level']", unique_paths)
        self.assertEqual(raw_keys, {"title", "skills", "name", "level"})

    def test_compute_path_values_comparison(self):
        docs = [
            {
                "_id": "doc_1",
                "parserResponseV1": {
                    "parserJson": {
                        "skills": [{"title": "Python"}, {"title": "SQL"}]
                    }
                },
                "parserResponseV3": {
                    "parserJson": {
                        "skills": [{"title": "Python"}, {"title": "Go"}]
                    }
                }
            },
            {
                "_id": "doc_2",
                "parserResponseV1": {
                    "parserJson": {
                        "skills": [{"title": "Java"}]
                    }
                },
                "parserResponseV3": {
                    "parserJson": {
                        "skills": [{"title": "Java"}, {"title": "Docker"}]
                    }
                }
            }
        ]
        path = "root['skills'][*]['title']"
        summary, doc_values_map = compute_path_values_comparison(docs, path)

        self.assertEqual(summary.path, path)
        self.assertEqual(summary.total_v1_values_count, 3)  # python, sql, java
        self.assertEqual(summary.total_v3_values_count, 4)  # python, go, java, docker
        self.assertEqual(summary.common_values_count, 2)    # python, java
        self.assertEqual(summary.added_values_count, 2)     # docker, go
        self.assertEqual(summary.removed_values_count, 1)   # sql
        self.assertEqual(summary.common_values, ["java", "python"])
        self.assertEqual(summary.added_values, ["docker", "go"])
        self.assertEqual(summary.removed_values, ["sql"])

        # Per doc checks
        self.assertEqual(doc_values_map["doc_1"]["common"], ["python"])
        self.assertEqual(doc_values_map["doc_1"]["added"], ["go"])
        self.assertEqual(doc_values_map["doc_1"]["removed"], ["sql"])

        self.assertEqual(doc_values_map["doc_2"]["common"], ["java"])
        self.assertEqual(doc_values_map["doc_2"]["added"], ["docker"])
        self.assertEqual(doc_values_map["doc_2"]["removed"], [])

    @unittest.skipUnless(HAS_TESTCLIENT, "TestClient requires httpx")
    def test_api_connect_and_preview(self):
        # Test connect with local mongo
        conn_res = self.client.post("/api/connect", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3"
        })
        self.assertEqual(conn_res.status_code, 200)
        conn_json = conn_res.json()
        self.assertEqual(conn_json["status"], "connected")
        self.assertIn("total_documents", conn_json)

        # Test preview
        prev_res = self.client.post("/api/preview", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3",
            "sample_size": 2
        })
        self.assertEqual(prev_res.status_code, 200)
        prev_json = prev_res.json()
        self.assertGreater(len(prev_json["sample_documents"]), 0)
        self.assertGreater(len(prev_json["suggested_paths"]), 0)

    @unittest.skipUnless(HAS_TESTCLIENT, "TestClient requires httpx")
    def test_api_analyze_and_export(self):
        # Test analyze pipeline on location path
        res = self.client.post("/api/analyze", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3",
            "path": "root['details']['locations'][*]['text']"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("summary", data)
        self.assertGreater(data["summary"]["total_documents"], 0)
        self.assertIn("chart_data", data)
        self.assertGreater(len(data["documents"]), 0)
        self.assertIn("path_values_summary", data)
        self.assertIsNotNone(data["path_values_summary"])
        self.assertEqual(data["path_values_summary"]["path"], "root['details']['locations'][*]['text']")

        # Test CSV export
        csv_res = self.client.post("/api/export/csv", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3",
            "path": "root['details']['locations'][*]['text']"
        })
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn("text/csv", csv_res.headers.get("content-type", ""))
        self.assertIn("document_id,v1_count,v3_count", csv_res.text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
