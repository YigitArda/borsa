import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// Simple StatCard component test
function StatCard({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="text-sm text-slate-400">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${highlight ? "text-yellow-400" : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}

describe("StatCard", () => {
  it("renders label and value", () => {
    render(<StatCard label="Test Label" value={42} />);
    expect(screen.getByText("Test Label")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("applies highlight style when highlight is true", () => {
    render(<StatCard label="Highlighted" value={100} highlight />);
    const valueElement = screen.getByText("100");
    expect(valueElement).toHaveClass("text-yellow-400");
  });

  it("applies default style when highlight is false", () => {
    render(<StatCard label="Normal" value={50} />);
    const valueElement = screen.getByText("50");
    expect(valueElement).toHaveClass("text-white");
  });
});
