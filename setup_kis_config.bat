@echo off
setlocal

cd /d "%~dp0"

echo This creates kis_config.local.env for KIS paper trading.
echo The file stays on this machine and is ignored by git.
echo.

:read_app_key
set /p KIS_APP_KEY=KIS app key:
if "%KIS_APP_KEY%"=="" (
    echo KIS app key is required.
    goto read_app_key
)

:read_app_secret
set /p KIS_APP_SECRET=KIS app secret:
if "%KIS_APP_SECRET%"=="" (
    echo KIS app secret is required.
    goto read_app_secret
)

:read_account
set /p KIS_ACCOUNT_NO=KIS account number, 8 digits:
if "%KIS_ACCOUNT_NO%"=="" (
    echo KIS account number is required.
    goto read_account
)
set /p KIS_ACCOUNT_PRODUCT_CODE=KIS account product code [01]:
if "%KIS_ACCOUNT_PRODUCT_CODE%"=="" set KIS_ACCOUNT_PRODUCT_CODE=01
set /p TELEGRAM_BOT_TOKEN=Telegram bot token [skip]:
set /p TELEGRAM_CHAT_ID=Telegram chat id [skip]:

(
echo KIS_APP_KEY=%KIS_APP_KEY%
echo KIS_APP_SECRET=%KIS_APP_SECRET%
echo KIS_ACCOUNT_NO=%KIS_ACCOUNT_NO%
echo KIS_ACCOUNT_PRODUCT_CODE=%KIS_ACCOUNT_PRODUCT_CODE%
echo KIS_ENV=paper
echo KIS_ENABLE_ORDERS=true
echo TELEGRAM_BOT_TOKEN=%TELEGRAM_BOT_TOKEN%
echo TELEGRAM_CHAT_ID=%TELEGRAM_CHAT_ID%
) > kis_config.local.env

echo.
echo Saved kis_config.local.env
echo Paper orders are enabled for KIS_ENV=paper.
pause
