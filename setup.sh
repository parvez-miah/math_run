#!/bin/bash

# Math Question Processor - Setup Script
# This script helps you set up the project structure

echo "=================================="
echo "📚 Math Question Processor Setup"
echo "=================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if folder_contexts.json exists
if [ ! -f "folder_contexts.json" ]; then
    echo -e "${YELLOW}⚠️  folder_contexts.json not found!${NC}"
    echo "Creating example folder_contexts.json..."
    cat > folder_contexts.json << 'EOF'
{
  "folders": [
    {
      "name": "First",
      "context": {
        "grades": [11, 12],
        "exam_types": ["Medical Admission", "HSC", "Versity", "Engineering Exam", "GST Exam"],
        "subject": "Higher Mathematics 1st Paper",
        "question_type": "MCQ",
        "chapter_en": "Differentiation",
        "chapter_bn": "অন্তরীকরণ",
        "chapter_number_en": "09",
        "chapter_number_bn": "০৯",
        "question_for_en": "Agricultural University Admission",
        "question_for_bn": "কৃষি বিশ্ববিদ্যালয় ভর্তি"
      }
    }
  ]
}
EOF
    echo -e "${GREEN}✅ Created folder_contexts.json${NC}"
else
    echo -e "${GREEN}✅ folder_contexts.json exists${NC}"
fi

# Create folder structure
echo ""
echo "Creating folder structure..."

# Read folders from folder_contexts.json
if command -v python3 &> /dev/null; then
    FOLDERS=$(python3 -c "
import json
with open('folder_contexts.json', 'r') as f:
    data = json.load(f)
    print(' '.join([folder['name'] for folder in data['folders']]))
" 2>/dev/null)
    
    if [ -n "$FOLDERS" ]; then
        for folder in $FOLDERS; do
            mkdir -p "Images/$folder"
            echo -e "${GREEN}✅ Created Images/$folder/${NC}"
        done
    else
        echo -e "${YELLOW}⚠️  Could not parse folder names, creating default structure${NC}"
        mkdir -p Images/First
        mkdir -p Images/Second
        mkdir -p Images/Third
        echo -e "${GREEN}✅ Created default folders${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Python not found, creating default structure${NC}"
    mkdir -p Images/First
    mkdir -p Images/Second
    mkdir -p Images/Third
    echo -e "${GREEN}✅ Created default folders${NC}"
fi

# Create output folder
mkdir -p output_data
echo -e "${GREEN}✅ Created output_data/ folder${NC}"

# Create .gitignore if it doesn't exist
if [ ! -f ".gitignore" ]; then
    echo "Creating .gitignore..."
    cat > .gitignore << 'EOF'
# Output data
output_data/
*.json.bak

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Virtual environment
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Logs
*.log

# Temp files
*.tmp
EOF
    echo -e "${GREEN}✅ Created .gitignore${NC}"
else
    echo -e "${GREEN}✅ .gitignore exists${NC}"
fi

# Check for GitHub workflow
if [ ! -d ".github/workflows" ]; then
    echo ""
    echo -e "${YELLOW}⚠️  .github/workflows/ directory not found!${NC}"
    echo "Creating GitHub workflow directory..."
    mkdir -p .github/workflows
    echo -e "${GREEN}✅ Created .github/workflows/${NC}"
    echo -e "${YELLOW}⚠️  Don't forget to add process_questions.yml workflow file!${NC}"
else
    echo -e "${GREEN}✅ .github/workflows/ exists${NC}"
fi

# Summary
echo ""
echo "=================================="
echo "📊 Setup Summary"
echo "=================================="
echo ""
echo "Folder Structure:"
ls -R Images/ 2>/dev/null || echo "  (Empty - add your images)"
echo ""
echo "Next Steps:"
echo ""
echo "1. 📁 Add your images to Images/[folder]/"
echo "   - Name format: 001.jpg, 002.jpg, etc."
echo ""
echo "2. ✏️  Edit folder_contexts.json"
echo "   - Update contexts for each folder"
echo "   - Add/remove folders as needed"
echo ""
echo "3. 🔑 Set up GitHub Secret:"
echo "   - Go to: Settings → Secrets → Actions"
echo "   - Name: GEMINI_API_KEYS"
echo "   - Value: key1,key2,key3,..."
echo ""
echo "4. 📤 Commit and push:"
echo "   git add ."
echo "   git commit -m 'Initial setup'"
echo "   git push origin main"
echo ""
echo "5. ▶️  Run workflow:"
echo "   - Go to Actions tab"
echo "   - Select 'Process Math Questions'"
echo "   - Click 'Run workflow'"
echo ""
echo "=================================="
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo "=================================="