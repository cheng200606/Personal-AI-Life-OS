export interface SharedCapture {
  title: string;
  text: string;
  url: string;
  receivedAt: string;
  expiresAt: number;
}

export type NotificationEnableResult =
  | { status: "enabled" | "already-enabled" }
  | { status: "denied" | "unsupported" | "failed"; message: string };

const SHARE_CACHE = "lifeos-share-inbox-v1";
const SHARE_KEY = "/__lifeos_pending_share__";

const SHARE_TTL_MS = 15 * 60 * 1000;

function cleanPart(value: unknown, limit: number): string {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

export function normalizeSharedCapture(value: unknown): SharedCapture {
  const input = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const now = Date.now();
  return {
    title: cleanPart(input.title, 200),
    text: cleanPart(input.text, 20000),
    url: cleanPart(input.url, 2000),
    receivedAt: cleanPart(input.receivedAt, 64) || new Date(now).toISOString(),
    expiresAt: typeof input.expiresAt === "number" && Number.isFinite(input.expiresAt)
      ? input.expiresAt
      : now + SHARE_TTL_MS,
  };
}

export function sharedCaptureBody(shared: SharedCapture): string {
  return [shared.text, shared.url].filter(Boolean).join("\n\n").slice(0, 20000);
}

export async function readPendingSharedCapture(): Promise<SharedCapture | null> {
  if (!("caches" in window)) return null;
  const cache = await caches.open(SHARE_CACHE);
  const response = await cache.match(SHARE_KEY);
  if (!response) return null;
  await cache.delete(SHARE_KEY);
  try {
    const shared = normalizeSharedCapture(await response.json());
    return shared.expiresAt > Date.now() ? shared : null;
  } catch {
    return null;
  }
}

export async function clearPendingSharedCapture(): Promise<void> {
  if (!("caches" in window)) return;
  const cache = await caches.open(SHARE_CACHE);
  await cache.delete(SHARE_KEY);
}

export function trackLifeosClientFocus(): void {
  if (!("serviceWorker" in navigator)) return;
  const announce = () => {
    if (document.visibilityState === "visible") navigator.serviceWorker.controller?.postMessage({ type: "lifeos-focus" });
  };
  window.addEventListener("focus", announce);
  document.addEventListener("visibilitychange", announce);
  navigator.serviceWorker.addEventListener("controllerchange", announce);
  announce();
}

export function registerLifeosServiceWorker(): void {
  if (!("serviceWorker" in navigator) || !import.meta.env.PROD) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // The application and download fallback remain available without offline support.
    });
  });
}

export async function enableDueNotifications(dueCount: number, url = '/'): Promise<NotificationEnableResult> {
  if (!("Notification" in window)) {
    return { status: "unsupported", message: "此浏览器不支持通知，应用内提醒仍可用。" };
  }
  try {
    const previousPermission = Notification.permission;
    const permission = previousPermission === "default"
      ? await Notification.requestPermission()
      : previousPermission;
    if (permission !== "granted") {
      return { status: "denied", message: "通知未获授权，应用内提醒仍可用。" };
    }
    const registration = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error("Service Worker timeout")), 5000)),
    ]);
    await registration.showNotification("Life OS 提醒", {
      body: dueCount > 0
        ? `你有 ${dueCount} 条到期或逾期提醒，打开应用查看。`
        : "浏览器通知已启用；有到期提醒时会在这里显示。",
      icon: "/icons/pwa-192.png",
      tag: "lifeos-due-reminders",
      data: { url },
    });
    return { status: previousPermission === "granted" ? "already-enabled" : "enabled" };
  } catch {
    return { status: "failed", message: "通知发送失败，不影响记录、复盘或捕获。" };
  }
}
