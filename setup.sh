#!/bin/bash
# setup.sh — Copies your files into replica1/, replica2/, replica3/
# Run this once before docker compose up --build
# Shrivadhu — Week 2 + Week 3

echo "========================================"
echo "MiniRAFT — Setting up replica folders"
echo "========================================"

YOUR_FILES="index.py log.py replication.py rpc.py sync.py Dockerfile requirements.txt"

for i in 1 2 3; do
  dir="replica${i}"
  echo ""
  echo "Setting up $dir/..."
  mkdir -p "$dir"

  for f in $YOUR_FILES; do
    if [ -f "$f" ]; then
      cp "$f" "$dir/$f"
      echo "  ✅ Copied $f → $dir/$f"
    else
      echo "  ❌ WARNING: $f not found — skipping"
    fi
  done
done

# # Create gateway folder if missing
# if [ ! -d "gateway" ]; then
#   echo ""
#   echo "Creating gateway/ placeholder..."
#   mkdir -p gateway
# fi

# Create frontend folder if missing
# if [ ! -d "frontend" ]; then
#   echo ""
#   echo "Creating frontend/ placeholder..."
#   mkdir -p frontend
#   echo "<h1>Frontend placeholder</h1>" > frontend/index.html
# fi

echo ""
echo "========================================"
echo "Done! Folder structure:"
echo "========================================"
ls -la

echo ""
echo "Next steps:"
echo "  1. Run: docker compose up --build"
echo "  2. Check: curl http://localhost:5001/status"
echo "  3. Check: curl http://localhost:5002/status"
echo "  4. Check: curl http://localhost:5003/status"
