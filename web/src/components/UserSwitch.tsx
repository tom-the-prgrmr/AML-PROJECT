import { useEffect, useState } from "react";
import { ApiError, apiGet, clearStoredUser, getStoredUser, storeUser } from "../api/client";
import type { Me } from "../api/types";

/** Shows the current actor and role, and lets the user switch to another actor. */
export default function UserSwitch({ onChange }: { onChange: () => void }) {
  const [me, setMe] = useState<Me | null>(null);

  const load = () => {
    apiGet<Me>("/me")
      .then((envelope) => setMe(envelope.data))
      .catch((err: unknown) => {
        // A stored actor the server no longer knows: forget it and fall back to the default.
        if (err instanceof ApiError && err.code === "unknown_user" && getStoredUser()) {
          clearStoredUser();
          load();
          onChange();
          return;
        }
        setMe(null);
      });
  };

  useEffect(load, []);

  const pick = (actor: string) => {
    storeUser(actor);
    load();
    onChange();
  };

  if (!me) return <div className="user-switch muted">Chưa xác định người dùng</div>;
  return (
    <div className="user-switch">
      <span>
        <strong>{me.actor}</strong> / {me.role}
      </span>
      <select
        aria-label="Đổi người dùng"
        value={me.actor}
        onChange={(e) => pick(e.target.value)}
      >
        {me.users.map((u) => (
          <option key={u.actor} value={u.actor}>
            {u.actor}
          </option>
        ))}
      </select>
    </div>
  );
}
