import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { PageLoading } from "../design/components/PageLoading";
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
const ForwardedLeaguePage = lazy(() =>
  import("../features/league/forwarded/ForwardedLeaguePage").then((m) => ({
    default: m.ForwardedLeaguePage,
  })),
);
const ForwardedMemberGate = lazy(() =>
  import("../features/league/forwarded/ForwardedMemberGate").then((m) => ({
    default: m.ForwardedMemberGate,
  })),
);
const LeagueMemberVsPage = lazy(() =>
  import("../features/league/pages/LeagueMemberVsPage").then((m) => ({
    default: m.LeagueMemberVsPage,
  })),
);
const LeagueMemberHistoryPage = lazy(() =>
  import("../features/league/pages/LeagueMemberHistoryPage").then((m) => ({
    default: m.LeagueMemberHistoryPage,
  })),
);

const ReminderPage = lazy(() =>
  import("../features/reminder/ReminderPage").then((m) => ({ default: m.ReminderPage })),
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
            <Suspense fallback={<PageLoading label={messages.common.loading} />}>
              <Routes>
                <Route path="/" element={<LeagueEntryPage />} />
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
                      <LeagueGate
                        forwarded={
                          <ForwardedMemberGate>
                            <LeagueMemberPage />
                          </ForwardedMemberGate>
                        }
                      >
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
                      <LeagueGate
                        forwarded={
                          <ForwardedMemberGate>
                            <LeagueMemberHistoryPage />
                          </ForwardedMemberGate>
                        }
                      >
                        <LeagueMemberHistoryPage />
                      </LeagueGate>
                    }
                  />
                ))}
                {/* The member against the system's suggestion, week by week. */}
                {["/league/members/:entryId/vs", "/league/:leagueId/members/:entryId/vs"].map(
                  (root) => (
                    <Route
                      key={root}
                      path={root}
                      element={
                        <LeagueGate
                          forwarded={
                            <ForwardedMemberGate>
                              <LeagueMemberVsPage />
                            </ForwardedMemberGate>
                          }
                        >
                          <LeagueMemberVsPage />
                        </LeagueGate>
                      }
                    />
                  ),
                )}
                {/* How notifications are received: the reminder's page under the member's. It
                    reads no league data, so no gate stands in front of it. */}
                <Route
                  path="/league/:leagueId/members/:entryId/reminder"
                  element={<ReminderPage />}
                />
                {/* One FPL team on its own, from the forwarder's bundle: no league, so no
                    gate and no member step. */}
                <Route
                  path="/entry/:entryId"
                  element={
                    <ForwardedMemberGate standalone>
                      <LeagueMemberPage />
                    </ForwardedMemberGate>
                  }
                />
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
