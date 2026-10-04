import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { PageShell } from "../design/components/PageShell";
import { useChosenLeague } from "../features/league/identity/useChosenLeague";
import { useViewerEntry } from "../features/league/identity/useViewerEntry";
import { useLanguage } from "../i18n/context";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

const SquadPage = lazy(() =>
  import("../features/squad/pages/SquadPage").then((m) => ({ default: m.SquadPage })),
);
const MovesPage = lazy(() =>
  import("../features/moves/pages/MovesPage").then((m) => ({ default: m.MovesPage })),
);
const RivalsPage = lazy(() =>
  import("../features/rivals/pages/RivalsPage").then((m) => ({ default: m.RivalsPage })),
);
const LeagueEntryPage = lazy(() =>
  import("../features/league/pages/LeagueEntryPage").then((m) => ({ default: m.LeagueEntryPage })),
);
const LeaguePage = lazy(() =>
  import("../features/league/pages/LeaguePage").then((m) => ({ default: m.LeaguePage })),
);
const LeagueGate = lazy(() =>
  import("../features/league/pages/LeagueGate").then((m) => ({ default: m.LeagueGate })),
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
const LeagueMemberHistoryPage = lazy(() =>
  import("../features/league/pages/LeagueMemberHistoryPage").then((m) => ({
    default: m.LeagueMemberHistoryPage,
  })),
);
const AdminPage = lazy(() =>
  import("../features/admin/pages/AdminPage").then((m) => ({ default: m.AdminPage })),
);

const FixturesPage = lazy(() =>
  import("../features/fixtures/FixturesPage").then((m) => ({ default: m.FixturesPage })),
);
const ContributePage = lazy(() =>
  import("../features/contributions/ContributePage").then((m) => ({ default: m.ContributePage })),
);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function App() {
  return (
    <LanguageProvider>
      <LocalizedApp basename={import.meta.env.BASE_URL} />
    </LanguageProvider>
  );
}

function LocalizedApp({ basename }: { basename: string }) {
  const { messages } = useLanguage();
  // The member the visitor said they are, in memory only: 'Bu hafta' opens their page.
  const { viewer } = useViewerEntry();
  const { leagueId } = useChosenLeague();
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <PageShell viewer={viewer} chosenLeagueId={leagueId}>
          <RouteErrorBoundary>
            <Suspense fallback={<EmptyState title={messages.common.loading} />}>
              <Routes>
                <Route path="/" element={<LeagueEntryPage />} />
                <Route path="/gw/:season/:gameweek" element={<SquadPage />} />
                <Route path="/moves" element={<MovesPage />} />
                <Route path="/moves/:season/:gameweek" element={<MovesPage />} />
                <Route path="/rivals" element={<RivalsPage />} />
                <Route path="/rivals/:season/:gameweek" element={<RivalsPage />} />
                {/* Every league address names its league; the old shape without the
                    number goes through the gate, which rewrites it to the chosen league. */}
                {["/league", "/league/:leagueId"].map((root) => (
                  <Route
                    key={root}
                    path={root}
                    element={
                      <LeagueGate>
                        <LeaguePage />
                      </LeagueGate>
                    }
                  />
                ))}
                {["/league/members", "/league/:leagueId/members"].map((root) => (
                  <Route
                    key={root}
                    path={root}
                    element={
                      <LeagueGate>
                        <LeagueMembersPage />
                      </LeagueGate>
                    }
                  />
                ))}
                {["/league/members/:entryId", "/league/:leagueId/members/:entryId"].map((root) => (
                  <Route
                    key={root}
                    path={root}
                    element={
                      <LeagueGate>
                        <LeagueMemberPage />
                      </LeagueGate>
                    }
                  />
                ))}
                {[
                  "/league/members/:entryId/history",
                  "/league/:leagueId/members/:entryId/history",
                ].map((root) => (
                  <Route
                    key={root}
                    path={root}
                    element={
                      <LeagueGate>
                        <LeagueMemberHistoryPage />
                      </LeagueGate>
                    }
                  />
                ))}
                <Route path="/fixtures" element={<FixturesPage />} />
                <Route path="/contribute" element={<ContributePage />} />
                <Route path="/status" element={<StatusPage />} />
                <Route path="/admin" element={<AdminPage />} />
                <Route path="*" element={<EmptyState title={messages.shell.notFound} />} />
              </Routes>
            </Suspense>
          </RouteErrorBoundary>
        </PageShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
