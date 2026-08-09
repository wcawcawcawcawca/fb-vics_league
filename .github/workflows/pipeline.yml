name: Run Pennants Pipeline

# Triggers whenever a new/updated unified JSON (gzipped -- GitHub's browser
# upload caps at 25 MiB, and the raw JSON runs ~44 MiB; the bookmarklet
# auto-upload also produces gzip, since that's natively supported by browsers
# via CompressionStream with no external library) lands in data/, or
# manually via the "Run workflow" button in the Actions tab.
on:
  push:
    paths:
      - 'data/pennants_over_easy_unified.json.gz'
  workflow_dispatch: {}

# Needed so the workflow can commit the generated outputs back to the repo.
permissions:
  contents: write

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install openpyxl

      # The JSON is uploaded gzipped to stay under GitHub's 25 MiB browser
      # upload limit. Decompress it back to the plain path ci_pipeline.py expects.
      - name: Decompress data file
        run: gunzip -k -f data/pennants_over_easy_unified.json.gz

      # ci_pipeline.py wraps run_pipeline.py and exits non-zero if the
      # Step 4 IP reconciliation check fails -- this is what makes a bad
      # run show up as a red X on the commit instead of silently landing.
      - name: Run pipeline (Steps 1-4) with reconciliation gate
        run: python ci_pipeline.py

      - name: Organize outputs
        run: |
          mkdir -p output
          for f in current_roster.json step2_pool.json step3_fa_pool.json cmd_free_agents.xlsx step4_cells.json latest_summary.json; do
            if [ -f "$f" ]; then
              mv -f "$f" "output/$f"
            fi
          done

      - name: Commit results back to the repo
        run: |
          git config user.name "pennants-pipeline-bot"
          git config user.email "actions@github.com"
          git add output/
          if git diff --cached --quiet; then
            echo "No output changes to commit"
          else
            git commit -m "Auto-update pipeline outputs"
            git push
          fi
