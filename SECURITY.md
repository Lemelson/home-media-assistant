# Security / Безопасность

This is experimental software without a support SLA or a completed independent security audit. Only the current public version receives fixes on a best-effort basis.

Use GitHub's **Security → Report a vulnerability** when private reporting is available. If it is unavailable, open an issue containing only a request for a private contact channel; do not include exploit details, tokens, database files, addresses or personal data. Never paste a secret to demonstrate that it is a secret. Revoke an exposed credential with its issuer first; deleting a file or rewriting Git history does not invalidate it.

The agent and Transmission RPC must remain bound to loopback. Use an authenticated SSH tunnel between machines. Do not publish your runtime directory or deploy the bot as a public multi-user service. File permissions and a disk UUID check are partial safeguards, not isolation from a compromised host.

Для уязвимостей используйте приватный отчёт GitHub. Если он недоступен, попросите приватный канал без технических деталей в публичном issue. Не отправляйте токены, базы и личные данные. При утечке сначала отзовите секрет у провайдера: удаление из Git не делает его недействительным. Агент и RPC должны быть доступны только через loopback; для разных машин используйте SSH-туннель. Независимый полный аудит безопасности пока не проводился.
