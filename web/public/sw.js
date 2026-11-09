// The deadline reminder's service worker (ADR 0013): it shows the notification the reminder
// Worker sends and opens the member's page on a tap. It caches nothing and intercepts no
// request, so the site stays what the server sends. Registered only when a member turns the
// reminder on.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = null;
  try {
    payload = event.data ? event.data.json() : null;
  } catch {
    payload = null;
  }
  if (!payload || typeof payload.title !== "string") return;
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: typeof payload.body === "string" ? payload.body : "",
      // A notification shows no SVG; the home-screen icon is the same mark as a PNG.
      icon: "/apple-touch-icon.png",
      tag: typeof payload.gameweek === "number" ? `deadline-gw${payload.gameweek}` : "deadline",
      data: { url: typeof payload.url === "string" ? payload.url : "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(
    (event.notification.data && event.notification.data.url) || "/",
    self.location.origin,
  );
  if (url.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const open = clients.find((client) => "focus" in client);
      if (open) return open.navigate(url.href).then((client) => (client || open).focus());
      return self.clients.openWindow(url.href);
    }),
  );
});
