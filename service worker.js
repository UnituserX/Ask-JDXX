// --- START OF FILE static/service-worker.js ---
// --- Configuration ---
const CACHE_VERSION = 3; // Increment version to trigger update/cleanup
const CACHE_NAME = `askjdxx-cache-v${CACHE_VERSION}`;
const OFFLINE_URL = '/offline.html'; // Path to your offline fallback page in /app/templates/

// Paths that should always go to the network (unless offline)
const NETWORK_ONLY_PATHS = [ '/ask', '/clear_history', '/create-checkout-session', '/create-customer-portal-session', '/webhook' ];
const API_PREFIX = '/api/'; // Example prefix for other APIs

// Core application shell files to cache on install
// *** UPDATE THESE PATHS TO MATCH YOUR ACTUAL STATIC FILES ***
const urlsToCache = [
  '/', // Cache the root/index page (might need network-first if highly dynamic)
  OFFLINE_URL,
  '/static/css/style.css',
  '/static/js/app.js',
  // Add absolute paths to any other critical JS/CSS loaded in base.html
  // '/static/vendor/some-library.js',
  // Icons used in the manifest/UI that should work offline:
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  // '/static/icons/favicon.ico', // Optional
  // Cache the manifest itself
  '/static/manifest.json',
  // Cache JS libraries loaded via CDN? Risky due to potential updates/CORS issues.
  // Better to host them locally if offline support is critical.
  // 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css', // Example - Not recommended for offline
];

// --- Helper Functions ---
const isNetworkOnly = (path) => NETWORK_ONLY_PATHS.some(p => path === p) || path.startsWith(API_PREFIX);

const cacheResponse = (cacheName, request, response) => {
    if (response && response.status === 200 && response.type === 'basic') {
        const responseToCache = response.clone();
        caches.open(cacheName).then(cache => cache.put(request, responseToCache));
        // console.log('SW: Cached:', request.url);
    }
};

const networkFirst = async (event, cacheName) => {
    try {
        const networkResponse = await fetch(event.request);
        // Cache successful GET requests
        if (event.request.method === 'GET') {
             cacheResponse(cacheName, event.request, networkResponse);
        }
        return networkResponse;
    } catch (error) {
        console.warn('SW: Network request failed, trying cache...', event.request.url, error);
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) { return cachedResponse; }
        // Specific fallback for API calls if offline
        if (isNetworkOnly(new URL(event.request.url).pathname)) {
             console.warn('SW: Providing offline JSON for API request.');
             return new Response(JSON.stringify({ error: 'Offline', detail: 'Network unavailable.' }), {
                 headers: { 'Content-Type': 'application/json' }, status: 503
             });
        }
        // Fallback to offline page for navigation requests
        if (event.request.mode === 'navigate') {
             console.warn('SW: Providing offline HTML page.');
             return caches.match(OFFLINE_URL);
        }
        // For other failed requests (images, etc.), just return the error response
        return new Response("Network error", { status: 408, headers: { 'Content-Type': 'text/plain' } });
    }
};

const cacheFirst = async (event, cacheName) => {
     const cachedResponse = await caches.match(event.request);
     if (cachedResponse) {
         // console.log('SW: Serving from cache:', event.request.url);
         return cachedResponse;
     }
     // console.log('SW: Not in cache, fetching from network:', event.request.url);
     try {
        const networkResponse = await fetch(event.request);
        cacheResponse(cacheName, event.request, networkResponse); // Cache successful response
        return networkResponse;
     } catch (error) {
         console.error('SW: Cache miss and network fetch failed.', event.request.url, error);
         // Fallback to offline page for navigation requests
         if (event.request.mode === 'navigate') {
              return caches.match(OFFLINE_URL);
         }
         // Return generic error for other assets
         return new Response("Network error fetching resource", { status: 503, headers: { 'Content-Type': 'text/plain' } });
     }
 };

// --- Event Listeners ---
self.addEventListener('install', event => {
  console.log('SW: Installing...');
  self.skipWaiting(); // Activate worker immediately
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('SW: Caching app shell...');
        // Use addAll which rejects if any request fails
        return cache.addAll(urlsToCache);
      })
      .then(() => console.log('SW: App shell cached successfully.'))
      .catch(error => console.error('SW: App Shell Caching failed!', error))
  );
});

self.addEventListener('activate', event => {
  console.log('SW: Activating...');
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) { // Delete old caches
            console.log('SW: Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => {
         console.log('SW: Activation complete.');
         return self.clients.claim(); // Take control immediately
    })
  );
});

self.addEventListener('fetch', event => {
  const requestUrl = new URL(event.request.url);

  // Ignore non-http/https requests (e.g., chrome-extension://)
  if (!requestUrl.protocol.startsWith('http')) return;

  // Ignore requests to Stripe API (they need to go direct)
   if (requestUrl.hostname.includes('stripe.com')) return;

  // Network first for API calls and non-GET requests
  if (isNetworkOnly(requestUrl.pathname) || event.request.method !== 'GET') {
    event.respondWith(networkFirst(event, CACHE_NAME));
    return;
  }

  // Cache first for all other GET requests (assets, navigation)
  event.respondWith(cacheFirst(event, CACHE_NAME));
});
// --- END OF FILE static/service-worker.js ---