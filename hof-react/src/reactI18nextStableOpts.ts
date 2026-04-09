/**
 * Stable second argument for `useTranslation(ns, opts)`.
 * react-i18next defaults `opts` to `{}`, which is a **new object every render** and can
 * invalidate internal memoization / external-store subscriptions, contributing to
 * "Maximum update depth exceeded" together with other state updates (e.g. function calls).
 *
 * Align with host apps that set `react: { useSuspense: false }` in i18next init.
 */
export const HOF_REACT_I18N_OPTS = Object.freeze({ useSuspense: false as const });
