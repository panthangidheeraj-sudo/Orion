/**
 * Google Sign-In on Firebase Auth, plus the one place auth errors are turned
 * into words a person can act on.
 */
import { FirebaseError } from 'firebase/app'
import {
  GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut, type User,
} from 'firebase/auth'
import { firebaseAuth } from './firebase'

export interface AccountUser {
  uid: string
  displayName: string | null
  email: string | null
  photoURL: string | null
}

export const toAccountUser = (u: User): AccountUser => ({
  uid: u.uid, displayName: u.displayName, email: u.email, photoURL: u.photoURL,
})

/** Fires once with the restored session (or null), then on every change. */
export function watchAuth(cb: (user: AccountUser | null) => void): () => void {
  return onAuthStateChanged(firebaseAuth(), (u) => cb(u ? toAccountUser(u) : null))
}

export async function signInWithGoogle(): Promise<AccountUser> {
  const provider = new GoogleAuthProvider()
  provider.setCustomParameters({ prompt: 'select_account' })
  const cred = await signInWithPopup(firebaseAuth(), provider)
  return toAccountUser(cred.user)
}

export async function signOutUser(): Promise<void> {
  await signOut(firebaseAuth())
}

export interface Explained {
  title: string
  detail?: string
  /** The user simply changed their mind — no toast needed. */
  quiet?: boolean
}

export const errorCode = (err: unknown): string =>
  err instanceof FirebaseError ? err.code : ''

/** Auth and Firestore error codes → an Orion toast. Never includes secrets. */
export function explainFirebaseError(err: unknown): Explained {
  const code = errorCode(err)
  switch (code) {
    case 'auth/popup-closed-by-user':
    case 'auth/cancelled-popup-request':
    case 'auth/user-cancelled':
      return { title: 'Sign-in cancelled', detail: 'Nothing changed — Orion keeps working on this device.', quiet: code === 'auth/cancelled-popup-request' }
    case 'auth/popup-blocked':
      return { title: 'The sign-in window was blocked', detail: 'Allow pop-ups for this site, then choose Continue with Google again.' }
    case 'auth/network-request-failed':
    case 'unavailable':
      return { title: 'You’re offline', detail: 'Orion keeps working locally. Sign-in and sync resume when you’re back online.' }
    case 'auth/internal-error':
    case 'auth/web-storage-unsupported':
      return { title: 'Couldn’t reach Google sign-in', detail: 'Check your connection, and that pop-ups, cookies and content blockers allow accounts.google.com — then try again.' }
    case 'auth/unauthorized-domain':
      return { title: 'This address isn’t allowed to sign in', detail: 'Add it under Firebase Console → Authentication → Settings → Authorized domains.' }
    case 'auth/operation-not-allowed':
      return { title: 'Google sign-in is turned off', detail: 'Enable the Google provider in Firebase Authentication.' }
    case 'auth/invalid-api-key':
    case 'auth/api-key-not-valid.-please-pass-a-valid-api-key.':
    case 'auth/configuration-not-found':
      return { title: 'Firebase isn’t set up correctly', detail: 'Check the VITE_FIREBASE_* values in .env.local and restart the dev server.' }
    case 'auth/user-token-expired':
    case 'auth/requires-recent-login':
    case 'auth/user-disabled':
    case 'unauthenticated':
      return { title: 'Your session has ended', detail: 'Sign in again to resume cloud sync. Your data on this device is untouched.' }
    case 'auth/too-many-requests':
    case 'resource-exhausted':
      return { title: 'Too many attempts', detail: 'Wait a minute, then try again.' }
    case 'permission-denied':
      return { title: 'Cloud sync was refused', detail: 'Firestore rules blocked this write. Your data is still safe on this device.' }
    default:
      return {
        title: 'Something went wrong with your account',
        detail: code ? `Error code: ${code}. Orion keeps working on this device.` : 'Orion keeps working on this device.',
      }
  }
}
