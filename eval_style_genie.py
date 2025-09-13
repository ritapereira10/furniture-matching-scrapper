#!/usr/bin/env python3
"""
Style Genie Evaluation Script
Tests the API with different queries and validates outputs
"""

import requests
import json
from typing import Dict, Any, List, Optional
import time

class StyleGenieEvaluator:
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url
        self.results = []
        
    def test_query(self, query: str, expected_fields: Optional[Dict] = None) -> Dict[str, Any]:
        """Test a single query and evaluate the response"""
        print(f"\n🧪 Testing: '{query}'")
        
        try:
            response = requests.post(
                f"{self.base_url}/smart-search",
                json={"query": query},
                timeout=30
            )
            
            if response.status_code != 200:
                return {
                    "query": query,
                    "status": "ERROR",
                    "error": f"HTTP {response.status_code}",
                    "details": response.text
                }
            
            data = response.json()
            
            # Evaluate the response
            evaluation = self._evaluate_response(query, data, expected_fields)
            evaluation["query"] = query
            evaluation["raw_response"] = data
            
            self.results.append(evaluation)
            self._print_evaluation(evaluation)
            
            return evaluation
            
        except Exception as e:
            error_result = {
                "query": query,
                "status": "ERROR", 
                "error": str(e)
            }
            self.results.append(error_result)
            print(f"❌ ERROR: {e}")
            return error_result
    
    def _evaluate_response(self, query: str, data: Dict, expected_fields: Optional[Dict] = None) -> Dict[str, Any]:
        """Evaluate if the response matches expectations"""
        evaluation = {
            "status": "PASS",
            "issues": [],
            "stats": {},
            "search_terms_generated": None
        }
        
        # Check if response has correct structure
        if "parsed_query" not in data:
            evaluation["issues"].append("Missing 'parsed_query' field")
            evaluation["status"] = "FAIL"
        
        if "items" not in data:
            evaluation["issues"].append("Missing 'items' field") 
            evaluation["status"] = "FAIL"
            
        if evaluation["status"] == "FAIL":
            return evaluation
        
        # Extract parsed query info
        parsed_query = data["parsed_query"]
        items = data["items"]
        
        # Check for suggestions on generic queries
        if len(query.split()) <= 2:
            if "suggestions" in data:
                evaluation["stats"]["suggestions_provided"] = len(data["suggestions"])
            else:
                evaluation["issues"].append("Generic query should provide suggestions")
        
        # Evaluate parsed fields
        if expected_fields:
            for field, expected_value in expected_fields.items():
                actual_value = parsed_query.get(field)
                if actual_value != expected_value:
                    evaluation["issues"].append(f"Expected {field}='{expected_value}', got '{actual_value}'")
        
        # Stats about results
        evaluation["stats"] = {
            "items_found": len(items),
            "has_suggestions": "suggestions" in data,
            "suggestions_count": len(data.get("suggestions", [])),
            "parsed_fields": {k: v for k, v in parsed_query.items() if v is not None}
        }
        
        # Try to get search terms from raw response (for debugging)
        if "search_terms" in data:
            evaluation["search_terms_generated"] = data["search_terms"]
        
        # Validate item structure
        if items:
            sample_item = items[0]
            required_item_fields = ["title", "price", "currency", "url", "image", "source"]
            for field in required_item_fields:
                if field not in sample_item:
                    evaluation["issues"].append(f"Items missing required field: {field}")
        
        if evaluation["issues"]:
            evaluation["status"] = "PARTIAL" if items else "FAIL"
            
        return evaluation
    
    def _print_evaluation(self, eval_result: Dict):
        """Print evaluation results in a readable format"""
        status = eval_result["status"]
        if status == "PASS":
            print("✅ PASS")
        elif status == "PARTIAL":
            print("⚠️ PARTIAL")
        else:
            print("❌ FAIL")
        
        stats = eval_result.get("stats", {})
        print(f"   📊 Found {stats.get('items_found', 0)} items")
        
        if eval_result.get("search_terms_generated"):
            print(f"   🔍 Search terms: '{eval_result['search_terms_generated']}'")
        
        parsed_fields = stats.get("parsed_fields", {})
        if parsed_fields:
            print(f"   📝 Parsed: {parsed_fields}")
        
        if stats.get("has_suggestions"):
            print(f"   💡 Suggestions: {stats['suggestions_count']}")
        
        if eval_result.get("issues"):
            print("   ⚠️ Issues:")
            for issue in eval_result["issues"]:
                print(f"      - {issue}")
    
    def run_full_evaluation(self):
        """Run a comprehensive set of tests"""
        print("🎭 Style Genie Evaluation Suite")
        print("=" * 50)
        
        # Test cases with expected results
        test_cases = [
            {
                "query": "mid century living room",
                "expected": {"style": "mid century", "city": "Amsterdam"}
            },
            {
                "query": "vintage chair under €100 in Amsterdam", 
                "expected": {"item_type": "chair", "style": "vintage", "max_price": 100, "city": "Amsterdam"}
            },
            {
                "query": "chair",
                "expected": {"item_type": "chair", "city": "Amsterdam"}  # Should have suggestions
            },
            {
                "query": "industrial table Rotterdam",
                "expected": {"item_type": "table", "style": "industrial", "city": "Rotterdam"}
            },
            {
                "query": "scandinavian lamp",
                "expected": {"item_type": "lamp", "style": "scandinavian", "city": "Amsterdam"}
            },
            {
                "query": "cool retro couch",
                "expected": {"item_type": "couch", "style": "vintage", "city": "Amsterdam"}  # retro -> vintage
            }
        ]
        
        for test_case in test_cases:
            self.test_query(test_case["query"], test_case.get("expected"))
            time.sleep(1)  # Be nice to the API
        
        self._print_summary()
    
    def _print_summary(self):
        """Print overall evaluation summary"""
        print("\n" + "=" * 50)
        print("📋 EVALUATION SUMMARY")
        print("=" * 50)
        
        total = len(self.results)
        passed = len([r for r in self.results if r.get("status") == "PASS"])
        partial = len([r for r in self.results if r.get("status") == "PARTIAL"])
        failed = len([r for r in self.results if r.get("status") == "FAIL"])
        
        print(f"Total tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"⚠️ Partial: {partial}")
        print(f"❌ Failed: {failed}")
        
        if failed > 0:
            print("\n🔥 Failed tests:")
            for result in self.results:
                if result.get("status") == "FAIL":
                    print(f"  - '{result['query']}': {result.get('error', 'See issues above')}")
        
        success_rate = (passed + partial) / total * 100
        print(f"\n🎯 Success rate: {success_rate:.1f}%")
        
        if success_rate >= 80:
            print("🎉 Style Genie is working well!")
        elif success_rate >= 60:
            print("⚠️ Style Genie needs some improvements")
        else:
            print("🚨 Style Genie needs significant fixes")

def main():
    """Run the evaluation"""
    evaluator = StyleGenieEvaluator()
    
    # Check if server is running
    try:
        response = requests.get("http://localhost:5000/")
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"⚠️ Server responding but status: {response.status_code}")
    except:
        print("❌ Server not running! Start with: python main.py")
        return
    
    evaluator.run_full_evaluation()

if __name__ == "__main__":
    main()