export const AUTHENTICATED_FALLBACK_ERROR =
  "authenticated_fallback_requires_current_task_authorization";

export function requireAuthenticatedFallbackAuthorization(args) {
  if (args?.allow_authenticated_fallback !== true) {
    throw new Error(AUTHENTICATED_FALLBACK_ERROR);
  }
}
