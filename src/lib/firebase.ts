/**
 * Firebase — app, Auth and Firestore handles, created once and only when the
 * Web app config is present (VITE_FIREBASE_* in .env.local).
 *
 * Orion is local-first: nothing in the app depends on this module. Without a
 * config, `firebaseConfigured` is false, the Account panel says cloud sync is
 * not set up, and everything else keeps working from localStorage.
 *
 * The config values are public identifiers of the Web app (they are shipped
 * to every browser that loads it); access is enforced by Firestore rules
 * scoped to the signed-in uid. They are still never logged.
 */
import { getApp, getApps, initializeApp, type FirebaseApp, type FirebaseOptions } from 'firebase/app'
import { browserLocalPersistence, getAuth, setPersistence, type Auth } from 'firebase/auth'
import {
  getFirestore, initializeFirestore, persistentLocalCache, persistentMultipleTabManager,
  type Firestore,
} from 'firebase/firestore'

const env = import.meta.env

const config: FirebaseOptions = {
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: env.VITE_FIREBASE_APP_ID,
}

/** Auth + Firestore need these four; the rest are optional for this app. */
export const firebaseConfigured = Boolean(
  config.apiKey && config.authDomain && config.projectId && config.appId,
)

let app: FirebaseApp | null = null
let auth: Auth | null = null
let db: Firestore | null = null

function firebaseApp(): FirebaseApp {
  if (!firebaseConfigured) throw new Error('Firebase is not configured')
  if (!app) app = getApps().length ? getApp() : initializeApp(config)
  return app
}

export function firebaseAuth(): Auth {
  if (!auth) {
    auth = getAuth(firebaseApp())
    // Survive refreshes and restarts (this is also the web default; being
    // explicit keeps it from changing under us).
    void setPersistence(auth, browserLocalPersistence).catch(() => { /* storage blocked: session-only */ })
  }
  return auth
}

export function firestore(): Firestore {
  if (!db) {
    const a = firebaseApp()
    try {
      // IndexedDB cache: reads work offline and writes made offline are queued
      // and sent when the connection returns — even across a reload.
      db = initializeFirestore(a, {
        localCache: persistentLocalCache({ tabManager: persistentMultipleTabManager() }),
      })
    } catch {
      // Already initialised (HMR) or IndexedDB unavailable (private mode).
      db = getFirestore(a)
    }
  }
  return db
}
