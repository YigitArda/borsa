import { api } from "@/lib/api";

describe("API client", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  describe("get", () => {
    it("returns parsed JSON on success", async () => {
      const mockData = [{ id: 1, ticker: "AAPL" }];
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => mockData,
      } as Response);

      const result = await api.get("/stocks");
      expect(result).toEqual(mockData);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/stocks"),
        expect.objectContaining({ cache: "no-store" })
      );
    });

    it("throws on non-ok response", async () => {
      global.fetch = jest.fn().mockResolvedValue({
        ok: false,
        status: 500,
      } as Response);

      await expect(api.get("/stocks")).rejects.toThrow("API error 500: /stocks");
    });
  });

  describe("post", () => {
    it("sends JSON body and returns response", async () => {
      const mockResponse = { task_id: "abc-123", status: "queued" };
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await api.post("/pipeline/ingest", { tickers: ["AAPL"] });
      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/pipeline/ingest"),
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tickers: ["AAPL"] }),
        })
      );
    });

    it("throws on non-ok response", async () => {
      global.fetch = jest.fn().mockResolvedValue({
        ok: false,
        status: 422,
      } as Response);

      await expect(api.post("/strategies/1/promote", {})).rejects.toThrow(
        "API error 422: /strategies/1/promote"
      );
    });
  });

  describe("new endpoints", () => {
    it("fetches jobs list", async () => {
      const mockJobs = [{ id: 1, job_name: "ingest", status: "completed" }];
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => mockJobs,
      } as Response);

      const result = await api.get("/admin/jobs");
      expect(result).toEqual(mockJobs);
    });

    it("fetches selected stocks", async () => {
      const mockStocks = [{ ticker: "AAPL", selected: true }];
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => mockStocks,
      } as Response);

      const result = await api.get("/selected-stocks");
      expect(result).toEqual(mockStocks);
    });

    it("triggers export", async () => {
      const mockExport = { url: "http://example.com/export.csv" };
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => mockExport,
      } as Response);

      const result = await api.post("/export", { format: "csv" });
      expect(result).toEqual(mockExport);
    });

    it("toggles kill switch", async () => {
      const mockResponse = { enabled: true };
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await api.post("/admin/kill-switch", { enabled: true });
      expect(result).toEqual(mockResponse);
    });
  });
});
