import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { PageShell } from "../design/components/PageShell";

const ThisWeekPage = lazy(() =>
  import("../features/this-week/pages/ThisWeekPage").then((m) => ({ default: m.ThisWeekPage })),
);
const HistoryPage = lazy(() =>
  import("../features/history/pages/HistoryPage").then((m) => ({ default: m.HistoryPage })),
);
const WhyPage = lazy(() =>
  import("../features/why/pages/WhyPage").then((m) => ({ default: m.WhyPage })),
);
const StatusPage = lazy(() =>
  import("../features/status/pages/StatusPage").then((m) => ({ default: m.StatusPage })),
);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function App({ basename = import.meta.env.BASE_URL }: { basename?: string }) {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <PageShell>
          <Suspense fallback={<EmptyState title="Loading…" />}>
            <Routes>
              <Route path="/" element={<ThisWeekPage />} />
              <Route path="/gw/:season/:gameweek" element={<ThisWeekPage />} />
              <Route path="/why/:season/:gameweek" element={<WhyPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/status" element={<StatusPage />} />
              <Route path="*" element={<EmptyState title="There is no page here." />} />
            </Routes>
          </Suspense>
        </PageShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
