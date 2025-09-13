#!/usr/bin/env python3
"""
Evaluation script specifically for all predefined Style Genie quick-search prompts
These MUST work perfectly for the user experience
"""

import requests
import json
import time

class PredefinedPromptsEvaluator:
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url
        
    def test_predefined_prompts(self):
        """Test all predefined quick-search prompts from the UI"""
        print("🎯 EVALUATING ALL PREDEFINED PROMPTS")
        print("=" * 60)
        print("These prompts MUST work perfectly - they're what users click!")
        print()
        
        # These are the exact prompts from the quick-search buttons
        predefined_tests = [
            {
                "display_name": "🪑 Mid Century Chair",
                "english_query": "mid century chair",
                "dutch_terms": "teak stoel",
                "min_expected_results": 10
            },
            {
                "display_name": "🌿 Mid Century Table", 
                "english_query": "mid century table",
                "dutch_terms": "teak tafel",
                "min_expected_results": 10
            },
            {
                "display_name": "🎨 Vintage Chair",
                "english_query": "vintage chair", 
                "dutch_terms": "vintage stoel",
                "min_expected_results": 10
            },
            {
                "display_name": "💡 Design Lamp",
                "english_query": "design lamp",
                "dutch_terms": "lamp design", 
                "min_expected_results": 10
            },
            {
                "display_name": "⚙️ Industrial Style",
                "english_query": "industrial style",
                "dutch_terms": "industrieel metaal",
                "min_expected_results": 5
            },
            {
                "display_name": "🌿 Scandinavian Wood",
                "english_query": "scandinavian wood",
                "dutch_terms": "licht hout",
                "min_expected_results": 5
            }
        ]
        
        results = []
        for test in predefined_tests:
            print(f"🧪 Testing: {test['display_name']}")
            print(f"   English: '{test['english_query']}'")
            print(f"   Dutch: '{test['dutch_terms']}'")
            
            result = self._test_single_prompt(test)
            results.append(result)
            
            # Print immediate result
            status = "✅ PASS" if result['status'] == 'PASS' else f"❌ {result['status']}"
            print(f"   {status} - Found {result['items_count']} items")
            
            if result['issues']:
                for issue in result['issues']:
                    print(f"   ⚠️  {issue}")
            print()
            
            time.sleep(1)  # Be nice to the API
        
        self._print_summary(results)
        return results
    
    def _test_single_prompt(self, test_config):
        """Test a single predefined prompt"""
        result = {
            'display_name': test_config['display_name'],
            'english_query': test_config['english_query'],
            'dutch_terms': test_config['dutch_terms'],
            'status': 'PASS',
            'issues': [],
            'items_count': 0,
            'raw_response': None
        }
        
        try:
            # Test with English query (like user typing)
            response = requests.post(
                f"{self.base_url}/smart-search",
                json={"query": test_config['english_query']},
                timeout=30
            )
            
            if response.status_code != 200:
                result['status'] = 'FAIL'
                result['issues'].append(f"HTTP {response.status_code}")
                return result
            
            data = response.json()
            result['raw_response'] = data
            
            # Check if response has correct structure
            if "items" not in data:
                result['status'] = 'FAIL'
                result['issues'].append("No 'items' field in response")
                return result
            
            items = data["items"]
            result['items_count'] = len(items)
            
            # Check if we got enough results
            min_expected = test_config.get('min_expected_results', 5)
            if len(items) < min_expected:
                result['status'] = 'PARTIAL'
                result['issues'].append(f"Expected {min_expected}+ items, got {len(items)}")
            
            # Check if results seem relevant (basic sanity check)
            if len(items) == 0:
                result['status'] = 'FAIL'
                result['issues'].append("No results found")
            else:
                # Check if items have required fields
                sample_item = items[0]
                required_fields = ["title", "price", "url", "source"]
                for field in required_fields:
                    if field not in sample_item:
                        result['status'] = 'PARTIAL' 
                        result['issues'].append(f"Items missing field: {field}")
                
                # Quick relevance check - titles should contain furniture-related terms
                furniture_keywords = ['stoel', 'tafel', 'lamp', 'chair', 'table', 'kast', 'bank', 'teak', 'vintage']
                relevant_items = 0
                for item in items[:5]:  # Check first 5 items
                    title = item.get('title', '').lower()
                    if any(keyword in title for keyword in furniture_keywords):
                        relevant_items += 1
                
                if relevant_items < 3:  # Less than 3 out of 5 items seem relevant
                    result['status'] = 'PARTIAL'
                    result['issues'].append("Results don't seem furniture-related")
                    
        except Exception as e:
            result['status'] = 'FAIL'
            result['issues'].append(f"Error: {str(e)}")
        
        return result
    
    def _print_summary(self, results):
        """Print comprehensive summary"""
        print("=" * 60)
        print("📋 PREDEFINED PROMPTS EVALUATION SUMMARY")
        print("=" * 60)
        
        total = len(results)
        passed = len([r for r in results if r['status'] == 'PASS'])
        partial = len([r for r in results if r['status'] == 'PARTIAL']) 
        failed = len([r for r in results if r['status'] == 'FAIL'])
        
        print(f"Total predefined prompts: {total}")
        print(f"✅ Working perfectly: {passed}")
        print(f"⚠️  Partial issues: {partial}")
        print(f"❌ Completely broken: {failed}")
        print()
        
        if failed > 0:
            print("🚨 BROKEN PROMPTS (CRITICAL):")
            for result in results:
                if result['status'] == 'FAIL':
                    print(f"   ❌ {result['display_name']}")
                    for issue in result['issues']:
                        print(f"      - {issue}")
            print()
        
        if partial > 0:
            print("⚠️ PROMPTS WITH ISSUES:")
            for result in results:
                if result['status'] == 'PARTIAL':
                    print(f"   ⚠️ {result['display_name']} ({result['items_count']} items)")
                    for issue in result['issues']:
                        print(f"      - {issue}")
            print()
        
        success_rate = (passed / total) * 100
        print(f"🎯 Success Rate: {success_rate:.1f}%")
        
        if success_rate == 100:
            print("🎉 ALL PREDEFINED PROMPTS WORKING PERFECTLY!")
        elif success_rate >= 80:
            print("✅ Most prompts working, minor fixes needed")
        elif success_rate >= 50:
            print("⚠️ Several prompts need fixing")
        else:
            print("🚨 CRITICAL: Most predefined prompts are broken!")
        
        print()
        print("REQUIREMENTS:")
        print("- ALL predefined prompts must return 5+ relevant results")
        print("- Users click these buttons expecting instant magic ✨")
        print("- Any failures here break the core user experience")

def main():
    evaluator = PredefinedPromptsEvaluator()
    
    # Check if server is running
    try:
        response = requests.get("http://localhost:5000/")
        print("✅ Server is running")
    except:
        print("❌ Server not running! Start with: python main.py")
        return
    
    evaluator.test_predefined_prompts()

if __name__ == "__main__":
    main()