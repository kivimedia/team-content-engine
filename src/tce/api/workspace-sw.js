/* Service worker for the editorial workspace.
 *
 * It does one job: receive a push and show it. There is deliberately no offline
 * caching here. A stale cached shell that silently serves yesterday's topics
 * would be worse than a page that fails honestly, and the studio already owns
 * the offline story for the one thing that must survive a dead connection -
 * recording chunks, which go to IndexedDB from recording.js.
 */

self.addEventListener("install", function () {
  // Take over immediately rather than waiting for every tab to close. There is
  // one user with one phone; a worker stuck "waiting" just means no buzz.
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  var payload = { title: "TCE", body: "Something finished.", path: "/today" };
  if (event.data) {
    try {
      payload = Object.assign(payload, event.data.json());
    } catch (e) {
      payload.body = event.data.text() || payload.body;
    }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      // One tag per kind, so a second script finishing replaces the first
      // instead of stacking four identical banners on his lock screen.
      tag: payload.kind || "tce",
      renotify: true,
      data: { path: payload.path || "/today" },
      badge: undefined,
      icon: undefined
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var path = (event.notification.data && event.notification.data.path) || "/today";
  // The worker is registered at the app root, so its scope already carries the
  // /tce prefix when the app is mounted there.
  var target = new URL(path.replace(/^\//, ""), self.registration.scope).href;

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        // Reuse the tab he already has open rather than piling up windows.
        if (list[i].url.indexOf(self.registration.scope) === 0 && "focus" in list[i]) {
          list[i].navigate(target);
          return list[i].focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
