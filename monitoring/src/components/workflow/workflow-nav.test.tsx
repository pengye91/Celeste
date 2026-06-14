import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { WorkflowNav } from "./workflow-nav";

// next/link: render as a plain anchor so we can assert on href.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// Capture the current mocked workflow id so each test can vary it.
let mockWorkflowId = "test-workflow-id";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: mockWorkflowId }),
}));

describe("WorkflowNav", () => {
  beforeEach(() => {
    mockWorkflowId = "test-workflow-id";
  });

  it("renders absolute /workflows/{id}/{tab} hrefs for every tab", () => {
    render(<WorkflowNav activeTab="overview" />);

    const id = "test-workflow-id";
    const expected: Record<string, string> = {
      Overview: `/workflows/${id}`,
      Constellation: `/workflows/${id}/constellation`,
      "OPA Loop": `/workflows/${id}/opa-loop`,
      Security: `/workflows/${id}/security`,
      Workspaces: `/workflows/${id}/workspaces`,
      Saga: `/workflows/${id}/saga`,
      Escalation: `/workflows/${id}/escalation`,
    };

    for (const [label, href] of Object.entries(expected)) {
      const link = screen.getByRole("link", { name: label });
      expect(link).toHaveAttribute("href", href);
    }
  });

  it("uses the actual workflow id from route params (uuid)", () => {
    mockWorkflowId = "9fb22a38-595c-4189-9a86-5eee69db1e15";
    render(<WorkflowNav activeTab="opa-loop" />);

    const opaLoop = screen.getByRole("link", { name: "OPA Loop" });
    expect(opaLoop).toHaveAttribute(
      "href",
      "/workflows/9fb22a38-595c-4189-9a86-5eee69db1e15/opa-loop"
    );
  });

  it("does not drop the id by emitting a relative href", () => {
    render(<WorkflowNav activeTab="security" />);
    const security = screen.getByRole("link", { name: "Security" });
    const href = security.getAttribute("href");
    // Must be absolute and must not be the buggy relative form.
    expect(href?.startsWith("/workflows/")).toBe(true);
    expect(href).not.toBe("./security");
    expect(href).not.toBe("/workflows/security");
  });

  it("marks only the active tab as current", () => {
    render(<WorkflowNav activeTab="saga" />);
    const saga = screen.getByRole("link", { name: "Saga" });
    const overview = screen.getByRole("link", { name: "Overview" });
    expect(saga).toHaveAttribute("aria-current", "page");
    expect(overview).not.toHaveAttribute("aria-current");
  });
});
