from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


class SupabaseRest:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.supabase_url.rstrip("/")
        self.service_key = settings.supabase_service_role_key
        self.anon_key = settings.supabase_anon_key

    def _headers(self, *, service_role: bool = True, user_token: str | None = None) -> dict[str, str]:
        api_key = self.service_key if service_role else self.anon_key
        authorization = f"Bearer {user_token}" if user_token else f"Bearer {api_key}"
        return {
            "apikey": api_key,
            "authorization": authorization,
            "content-type": "application/json",
            "prefer": "return=representation",
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:1000]
            raise RuntimeError(f"Supabase HTTP error {response.status_code}: {body}") from exc

    async def get_user(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/auth/v1/user",
                headers={
                    "apikey": self.anon_key,
                    "authorization": f"Bearer {access_token}",
                },
            )
            self._raise_for_status(response)
            return response.json()

    async def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/auth/v1/admin/users",
                headers={
                    "apikey": self.service_key,
                    "authorization": f"Bearer {self.service_key}",
                },
                params={"page": 1, "per_page": 1000},
            )
            self._raise_for_status(response)
            payload = response.json()
        users = payload.get("users", payload if isinstance(payload, list) else [])
        target = email.lower()
        for user in users:
            if (user.get("email") or "").lower() == target:
                return user
        return None

    async def upsert(self, table: str, payload: dict[str, Any], on_conflict: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/rest/v1/{table}",
                params={"on_conflict": on_conflict},
                headers={**self._headers(), "prefer": "resolution=merge-duplicates,return=representation"},
                json=payload,
            )
            self._raise_for_status(response)
            return response.json()

    async def insert(self, table: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/rest/v1/{table}",
                headers=self._headers(),
                json=payload,
            )
            self._raise_for_status(response)
            return response.json()

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        or_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"select": columns}
        if filters:
            params.update(filters)
        if or_filter:
            params["or"] = or_filter
        if order:
            params["order"] = order
        if limit:
            params["limit"] = limit

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/rest/v1/{table}",
                headers=self._headers(),
                params=params,
            )
            self._raise_for_status(response)
            return response.json()

    async def patch(
        self,
        table: str,
        *,
        filters: dict[str, str],
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/rest/v1/{table}",
                headers=self._headers(),
                params=filters,
                json=payload,
            )
            self._raise_for_status(response)
            return response.json()
