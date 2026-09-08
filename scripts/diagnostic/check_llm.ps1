Write-Host "LLM Configuration Check"
Write-Host "-----------------------"

python -c "from backend.config import settings; print('Provider:', settings.LLM_PROVIDER); print('OpenAI configured:', bool(settings.OPENAI_API_KEY)); print('DeepSeek configured:', bool(settings.DEEPSEEK_API_KEY))" 2>&1
