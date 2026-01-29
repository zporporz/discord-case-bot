> ⚠️ **Railway-only Project**
>
> This Discord bot is designed to run **exclusively on Railway**.
> Local execution and other platforms are **not supported**.
>
> **Required via Railway Environment Variables:**
> - `DISCORD_TOKEN` – Discord bot token  
> - `DATABASE_URL` – PostgreSQL connection string (Railway plugin)  
> - `GOOGLE_SERVICE_ACCOUNT_JSON` – Full Google Service Account JSON  
>   *(must be provided as a single JSON string, not a file)*
>
> All Google Sheets access, database connections, and secrets **must be configured in Railway**.
>
> The bot updates and edits **existing pinned dashboard messages**  
> (it does **not** create duplicate dashboard messages).
>
> ⚠️ Running this code outside Railway may result in unexpected behavior or data inconsistency.
