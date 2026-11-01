import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { OpeningMark } from "../design/shell/OpeningMark";
import { useLanguage } from "../i18n/context";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { IdentifiedShell } from "./IdentifiedShell";
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
const ForwardedLeaguePage = lazy(() =>
  import("../features/league/forwarded/ForwardedLeaguePage").then((m) => ({
    default: m.ForwardedLeaguePage,
  })),
);
const ForwardedMemberPage = lazy(() =>
  import("../features/league/forwarded/ForwardedMemberPage").then((m) => ({
    default: m.ForwardedMemberPage,
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
      <OpeningMark />
    </LanguageProvider>
  );
}

function LocalizedApp({ basename }: { basename: string }) {
  const { messages } = useLanguage();
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        {/* The shell reads the visitor's league and member through the identity module. */}
        <IdentifiedShell>
          <RouteErrorBoundary>
            <Suspense fallback={<EmptyState title={messages.common.loading} />}>
              <Routes>
                <Route path="/" element={<LeagueEntryPage />} />
                {/* The system's own pages name no league; they stand behind the same two
                    steps as the league pages, for the visitor's current league. */}
                <Route
                  path="/gw/:season/:gameweek"
                  element={
                    <LeagueGate source="visitor">
                      <SquadPage />
                    </LeagueGate>
                  }
                />
                {["/moves", "/moves/:season/:gameweek"].map((path) => (
                  <Route
                    key={path}
                    path={path}
                    element={
                      <LeagueGate source="visitor">
                        <MovesPage />
                      </LeagueGate>
                    }
                  />
                ))}
                {["/rivals", "/rivals/:season/:gameweek"].map((path) => (
                  <Route
                    key={path}
                    path={path}
                    element={
                      <LeagueGate source="visitor">
                        <RivalsPage />
                      </LeagueGate>
                    }
                  />
                ))}
                {/* Every league address names its league; the old shape without the
                    number goes through the gate, which rewrites it to the current league.
                    The gate then asks who the visitor is before the page is drawn. A
                    classic league the site does not publish opens from the FPL forwarder
                    instead, as its standings (#983 step 4). */}
                {["/league", "/league/:leagueId"].map((root) => (
                  <Route
                    key={root}
                    path={root}
                    element={
                      <LeagueGate forwarded={<ForwardedLeaguePage />}>
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
                      <LeagueGate forwarded={<ForwardedLeaguePage />}>
                        <LeagueMembersPage />
                      </LeagueGate>
                    }
                  />
                ))}
                {/* A member's page and each of their tools: one route with the tool as an
                    optional last segment, so moving between them keeps the page mounted and
                    a plan the device computed stays. The history's own address ranks above
                    it, as a fixed segment does over a parameter. */}
                {[
                  "/league/members/:entryId/:tool?",
                  "/league/:leagueId/members/:entryId/:tool?",
                ].map((root) => (
                  <Route
                    key={root}
                    path={root}
                    element={
                      <LeagueGate forwarded={<ForwardedMemberPage />}>
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
                {/* One FPL team on its own, from the forwarder's bundle: no league, so no
                    gate and no member step. */}
                <Route path="/entry/:entryId" element={<ForwardedMemberPage />} />
                <Route path="/fixtures" element={<FixturesPage />} />
                {import.meta.env.VITE_ADVICE_API_ORIGIN && (
                  <Route path="/contribute" element={<ContributePage />} />
                )}
                <Route path="/status" element={<StatusPage />} />
                <Route path="/admin" element={<AdminPage />} />
                <Route path="*" element={<EmptyState title={messages.shell.notFound} />} />
              </Routes>
            </Suspense>
          </RouteErrorBoundary>
        </IdentifiedShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
