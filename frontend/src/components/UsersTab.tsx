import { useEffect, useState } from "react";
import { api, type User, type UserRole } from "../lib/api";
import { Icon } from "./Icon";

export function UsersTab({
  currentUserId,
  notify,
}: {
  currentUserId: string;
  notify: (message: string, kind?: "ok" | "error") => void;
}) {
  const [users, setUsers] = useState<User[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("viewer");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const result = await api.listUsers();
    setUsers(result.users);
  };

  useEffect(() => {
    load().catch((err: Error) => notify(err.message, "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = async () => {
    setBusy(true);
    try {
      await api.createUser({ email: email.trim(), password, role });
      setEmail("");
      setPassword("");
      setRole("viewer");
      await load();
      notify("User created.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const update = async (user: User, body: Parameters<typeof api.updateUser>[1]) => {
    try {
      await api.updateUser(user.id, body);
      await load();
      notify("User updated.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  const resetPassword = async (user: User) => {
    const next = window.prompt(`New password for ${user.email} (at least 8 characters)`);
    if (!next) return;
    if (next.length < 8) {
      notify("Password must be at least 8 characters.", "error");
      return;
    }
    await update(user, { password: next });
  };

  const remove = async (user: User) => {
    if (!window.confirm(`Delete ${user.email}? Their sessions will be revoked.`)) return;
    try {
      await api.deleteUser(user.id);
      await load();
      notify("User deleted.", "ok");
    } catch (err) {
      notify((err as Error).message, "error");
    }
  };

  return (
    <div className="tab-panel">
      <section className="settings-section">
        <h3>Add a user</h3>
        <div className="provider-grid">
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="person@example.com"
            />
          </label>
          <label className="field">
            <span>Password <small>· at least 8 characters</small></span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
            />
          </label>
          <label className="field">
            <span>Role</span>
            <select value={role} onChange={(event) => setRole(event.target.value as UserRole)}>
              <option value="viewer">Viewer — read and search</option>
              <option value="admin">Admin — full management</option>
            </select>
          </label>
        </div>
        <button
          className="button primary small"
          onClick={add}
          disabled={busy || !email.trim() || password.length < 8}
        >
          {busy ? <span className="spinner light" /> : <Icon name="plus" size={14} />} Add user
        </button>
      </section>

      <section className="settings-section">
        <h3>Users</h3>
        <div className="user-table">
          {users.map((user) => (
            <div className="user-row" key={user.id}>
              <div className="user-identity">
                <Icon name="user" size={16} />
                <div>
                  <strong>{user.email}</strong>
                  <small>{user.role === "admin" ? "Administrator" : "Viewer"}</small>
                </div>
              </div>
              <select
                value={user.role}
                disabled={user.id === currentUserId}
                onChange={(event) =>
                  update(user, { role: event.target.value as UserRole })
                }
              >
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </select>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={user.active}
                  disabled={user.id === currentUserId}
                  onChange={(event) => update(user, { active: event.target.checked })}
                />
                Active
              </label>
              <button className="button ghost small" onClick={() => resetPassword(user)}>
                Reset password
              </button>
              <button
                className="icon-button small danger"
                onClick={() => remove(user)}
                disabled={user.id === currentUserId}
                title="Delete user"
                aria-label="Delete user"
              >
                <Icon name="trash" size={15} />
              </button>
            </div>
          ))}
          {users.length === 0 && <p className="fine-print">No users found.</p>}
        </div>
      </section>

      <p className="fine-print">
        Viewers can read documents, search and ask questions. Admins can also add/remove documents,
        games, campaigns and users, and change AI settings.
      </p>
    </div>
  );
}
