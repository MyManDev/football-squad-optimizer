import { Component, type ReactNode } from "react";
import { useLocation } from "react-router";

import { EmptyState } from "../design/components/EmptyState";
import { useLanguage } from "../i18n/context";

/**
 * Catches a page that fails to render: a lazy route chunk an old tab asks for after a
 * deploy renamed it, or a document shape a component throws on. The shell and its
 * navigation stay; the page says it could not be drawn and offers a reload. Moving to
 * another address tries again.
 */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const { messages } = useLanguage();
  return (
    <Boundary
      resetKey={pathname}
      title={messages.common.pageFailed}
      body={messages.common.pageFailedBody}
      action={messages.common.reload}
    >
      {children}
    </Boundary>
  );
}

interface BoundaryProps {
  resetKey: string;
  title: string;
  body: string;
  action: string;
  children: ReactNode;
}

interface BoundaryState {
  failed: boolean;
  /** The address the failure happened at; another address clears it. */
  at: string;
}

class Boundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false, at: this.props.resetKey };

  static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState) {
    return props.resetKey !== state.at ? { failed: false, at: props.resetKey } : null;
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <EmptyState title={this.props.title}>
        <p>{this.props.body}</p>
        <button type="button" onClick={() => window.location.reload()}>
          {this.props.action}
        </button>
      </EmptyState>
    );
  }
}
