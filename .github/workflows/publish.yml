name: publish-daily-report

on:
  schedule:
    # UTC 22:00 = KST 07:00
    - cron: '0 22 * * *'
  workflow_dispatch:
    inputs:
      draft:
        description: '초안으로만 올리기'
        type: choice
        options: ['true', 'false']
        default: 'true'

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python scripts/publish.py
        env:
          PUBLISH_DRAFT:         ${{ github.event.inputs.draft || 'false' }}
          GEMINI_API_KEY:        ${{ secrets.GEMINI_API_KEY }}
          BLOGGER_CLIENT_ID:     ${{ secrets.BLOGGER_CLIENT_ID }}
          BLOGGER_CLIENT_SECRET: ${{ secrets.BLOGGER_CLIENT_SECRET }}
          BLOGGER_REFRESH_TOKEN: ${{ secrets.BLOGGER_REFRESH_TOKEN }}
          BLOG_ID:               ${{ secrets.BLOG_ID }}
          TELEGRAM_BOT_TOKEN:    ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID:      ${{ secrets.TELEGRAM_CHAT_ID }}
