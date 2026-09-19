import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Component, lazy, Suspense, type ReactNode } from "react";
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
const LeagueEntryPage = lazy(() =>
  import("../features/league/pages/LeagueEntryPage").then((m) => ({ default: m.LeagueEntryPage })),
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
const FixturePanels = lazy(() =>
  import("../features/fixtures/FixturePanels").then((m) => ({ default: m.FixturePanels })),
);

/** The fixture rails are a convenience: if their chunk fails to load, the page stays whole. */
class Optional extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

const rails = (
  <Optional>
    <Suspense fallback={null}>
      <FixturePanels />
    </Suspense>
  </Optional>
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
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <PageShell rails={rails}>
          <Suspense fallback={<EmptyState title={messages.common.loading} />}>
            <Routes>
              <Route path="/" element={<LeagueEntryPage />} />
              <Route path="/gw/:season/:gameweek" element={<SquadPage />} />
              <Route path="/moves" element={<MovesPage />} />
              <Route path="/moves/:season/:gameweek" element={<MovesPage />} />
              <Route path="/rivals" element={<RivalsPage />} />
              <Route path="/rivals/:season/:gameweek" element={<RivalsPage />} />
              <Route path="/league" element={<LeaguePage />} />
              <Route path="/league/members" element={<LeagueMembersPage />} />
              <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
              <Route
                path="/league/members/:entryId/history"
                element={<LeagueMemberHistoryPage />}
              />
              <Route path="/fixtures" element={<FixturesPage />} />
              <Route path="/status" element={<StatusPage />} />
              <Route path="/admin" element={<AdminPage />} />
              <Route path="*" element={<EmptyState title={messages.shell.notFound} />} />
            </Routes>
          </Suspense>
        </PageShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
