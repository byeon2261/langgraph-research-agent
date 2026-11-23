# Run LangGraph Studio dev server with UTF-8 mode (fixes cp949 UnicodeDecodeError on Windows)
$env:PYTHONUTF8 = "1"
uv run langgraph dev
