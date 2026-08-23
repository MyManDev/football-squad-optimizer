import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { PageShell } from "../design/components/PageShell";
import { useLanguage } from "../i18n/context";
import { LanguageProvider } from "../i18n/LanguageProvider";

const SquadPage = lazy(() =>
  import("../features/squad/pages/SquadPage").then((m) => ({ default: m.SquadPage })),
);
const MovesPage = lazy(() =>
  import("../features/moves/pages/MovesPage").then((m) => ({ default: m.MovesPage })),
);
const RivalsPage = lazy(() =>
  import("../features/rivals/pages/RivalsPage").then((m) => ({ default: m.RivalsPage })),
);
const LeaguePage = lazy(() =>
  import("../features/league/pages/LeaguePage").then((m) => ({ default: m.LeaguePage })),
);
const LeagueMembersPage = lazy(() =>
  import("../features/league/pages/LeagueMembersPage").then((m) => ({
    default: m.LeagueMembersPage,
  })),
);
const LeagueMemberPage = lazy(() =>
  import("../features/league/pages/LeagueMemberPage").then((m) => ({
    default: m.LeagueMemberPage,
  })),
);
const StatusPage = lazy(() =>
  import("../features/status/pages/StatusPage").then((m) => ({ default: m.StatusPage })),
);
const AnalysisPage = lazy(() =>
  import("../features/analysis/pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })),
);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function App({ basename = import.meta.env.BASE_URL }: { basename?: string }) {
  return (
    <LanguageProvider>
      <LocalizedApp basename={basename} />
    </LanguageProvider>
  );
}

function LocalizedApp({ basename }: { basename: string }) {
  const { messages } = useLanguage();
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <PageShell>
          <Suspense fallback={<EmptyState title={messages.common.loading} />}>
            <Routes>
              <Route path="/" element={<SquadPage />} />
              <Route path="/gw/:season/:gameweek" element={<SquadPage />} />
              <Route path="/moves" element={<MovesPage />} />
              <Route path="/moves/:season/:gameweek" element={<MovesPage />} />
              <Route path="/rivals" element={<RivalsPage />} />
              <Route path="/rivals/:season/:gameweek" element={<RivalsPage />} />
              <Route path="/league" element={<LeaguePage />} />
              <Route path="/league/members" element={<LeagueMembersPage />} />
              <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
              <Route path="/status" element={<StatusPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              <Route path="/analysis/:slug" element={<AnalysisPage />} />
              <Route path="*" element={<EmptyState title={messages.shell.notFound} />} />
            </Routes>
          </Suspense>
        </PageShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
