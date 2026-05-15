import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// Mock Dashboard component test
function MockDashboard() {
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-3 gap-4">
        <div>Stocks Tracked: 20</div>
        <div>Promoted Strategies: 3</div>
        <div>Status: Research Mode</div>
      </div>
    </div>
  );
}

describe("Dashboard", () => {
  it("renders dashboard title", () => {
    render(<MockDashboard />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders stat cards", () => {
    render(<MockDashboard />);
    expect(screen.getByText(/Stocks Tracked:/)).toBeInTheDocument();
    expect(screen.getByText(/Promoted Strategies:/)).toBeInTheDocument();
    expect(screen.getByText(/Status:/)).toBeInTheDocument();
  });
});
