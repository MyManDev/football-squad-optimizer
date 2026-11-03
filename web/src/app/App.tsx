import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { OpeningMark } from "../design/shell/OpeningMark";
import { useLanguage } from "../i18n/context";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { IdentifiedShell } from "./IdentifiedShell";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

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
const LeagueMemberHistoryPage = lazy(() =>
  import("../features/league/pages/LeagueMemberHistoryPage").then((m) => ({
    default: m.LeagueMemberHistoryPage,
  })),
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
                {/* Every league address names its league; the old shape without the
                    number goes through the gate, which rewrites it to the current league.
                    The gate then asks who the visitor is before the page is drawn. */}
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
                {import.meta.env.VITE_ADVICE_API_ORIGIN && (
                  <Route path="/contribute" element={<ContributePage />} />
                )}
                <Route path="*" element={<EmptyState page title={messages.shell.notFound} />} />
              </Routes>
            </Suspense>
          </RouteErrorBoundary>
        </IdentifiedShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
