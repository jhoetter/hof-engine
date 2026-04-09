# `@hof-engine/react`

React UI and hooks for hof-engine agent chat, tables, and related flows.

## i18n

Agent UI strings live in `locales/en/hofEngine.json` and `locales/de/hofEngine.json` (namespace **`hofEngine`**).

Host apps must register these resources on the **same** `i18next` instance they use for the rest of the app **before** rendering agent components, for example:

```ts
import i18n from "i18next";
import hofEngineEn from "@hof-engine/react/locales/en/hofEngine.json";
import hofEngineDe from "@hof-engine/react/locales/de/hofEngine.json";

i18n.addResourceBundle("en", "hofEngine", hofEngineEn, true, true);
i18n.addResourceBundle("de", "hofEngine", hofEngineDe, true, true);
```

Or merge them in your `resources` object alongside your other namespaces. The package lists `i18next` and `react-i18next` as peer dependencies; align versions with your app.

In the hof-os monorepo, spreadsheet-app imports these JSON files in `ui/lib/i18n.ts`. German stubs can be filled via `make translate` (hof-react target) when a sibling `hof-engine` checkout is present.
