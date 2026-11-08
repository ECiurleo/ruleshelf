import { useState } from "react";
import { api, type User } from "../lib/api";
import { Icon } from "./Icon";

export function LoginPage({
  theme,
  onToggleTheme,
  onLogin,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onLogin: (user: User) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.login(email.trim(), password);
      onLogin(result.user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <button className="icon-button login-theme" onClick={onToggleTheme} aria-label="Toggle theme">
        <Icon name={theme === "dark" ? "sun" : "moon"} size={19} />
      </button>
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <span className="brand-mark">
            <Icon name="book" size={22} />
          </span>
          <div>
            <strong>Ruleshelf</strong>
            <small>your rulebooks, searchable</small>
          </div>
        </div>
        <h1>Sign in</h1>
        <p className="login-sub">Use the account an administrator created for you.</p>
        <label className="field">
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            autoFocus
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
          />
        </label>
        {error && <p className="form-error">{error}</p>}
        <button className="button primary login-submit" type="submit" disabled={busy}>
          {busy ? <span className="spinner light" /> : <Icon name="lock" size={16} />}
          Sign in
        </button>
        <p className="login-foot">Ask an administrator if you need an account or a password reset.</p>
      </form>
    </div>
  );
}
