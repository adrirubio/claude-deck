#!/bin/bash
# Test script for Commands API endpoints

BASE_URL="http://localhost:8000/api/v1"

echo "======================================"
echo "Testing Commands API Endpoints"
echo "======================================"
echo ""

# Test 1: List all commands
echo "1. Testing GET /api/v1/commands"
curl -s "$BASE_URL/commands" | python3 -m json.tool
echo ""
echo ""

# Test 2: Get specific command
echo "2. Testing GET /api/v1/commands/user/plan-project.md"
curl -s "$BASE_URL/commands/user/plan-project.md" | python3 -m json.tool
echo ""
echo ""

# Test 3: Create a new command
echo "3. Testing POST /api/v1/commands (create test-command)"
curl -s -X POST "$BASE_URL/commands" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-command",
    "scope": "project",
    "description": "A test command for API verification",
    "allowed_tools": ["Read", "Write"],
    "content": "This is a test command.\n\nUsage: /test-command"
  }' | python3 -m json.tool
echo ""
echo ""

# Test 4: List commands again to see the new command
echo "4. Testing GET /api/v1/commands (should now include test-command)"
curl -s "$BASE_URL/commands" | python3 -m json.tool
echo ""
echo ""

# Test 5: Update the command
echo "5. Testing PUT /api/v1/commands/project/test-command.md"
curl -s -X PUT "$BASE_URL/commands/project/test-command.md" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated test command description",
    "content": "This is an UPDATED test command.\n\nUsage: /test-command <args>"
  }' | python3 -m json.tool
echo ""
echo ""

# Test 6: Delete the command
echo "6. Testing DELETE /api/v1/commands/project/test-command.md"
curl -s -X DELETE "$BASE_URL/commands/project/test-command.md" -w "\nHTTP Status: %{http_code}\n"
echo ""
echo ""

# Test 7: Verify deletion
echo "7. Testing GET /api/v1/commands (test-command should be gone)"
curl -s "$BASE_URL/commands" | python3 -m json.tool
echo ""
echo ""

echo "======================================"
echo "All tests completed!"
echo "======================================"
