// Window-scoped credentials: survive navigation/reload, never persist passwords.
export const accountStorageKey = "nitrogen_account_session";
export type StoredAccount = { token: string; username: string };
let memory: StoredAccount | null = null;
export function readAccount(): StoredAccount | null {
  if (typeof window === "undefined") return null;
  try {
    const value = JSON.parse(window.sessionStorage.getItem(accountStorageKey) || "null");
    memory = value && typeof value.token === "string" && typeof value.username === "string" ? value : null;
  } catch { /* Storage-disabled browsers retain the current in-memory session. */ }
  return memory;
}
export function storeAccount(account: StoredAccount | null) {
  memory = account;
  try {
    if (account) window.sessionStorage.setItem(accountStorageKey, JSON.stringify(account));
    else window.sessionStorage.removeItem(accountStorageKey);
  } catch { /* Navigation within the app still works when storage is disabled. */ }
}
export function accountHeaders(): Record<string, string> {
  const account = readAccount();
  return account ? { Authorization: `Bearer ${account.token}` } : {};
}
export function expireAccount(token?: string) {
  window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
}
