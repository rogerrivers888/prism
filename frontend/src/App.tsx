import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Placeholder } from "./components/Placeholder";
import { Universe } from "./routes/Universe";
import { ThemeProvider } from "./theme/ThemeProvider";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<Universe />} />
              <Route path="/company/:ticker" element={<Placeholder title="Company" />} />
              <Route path="/screener" element={<Placeholder title="Screener" />} />
              <Route path="/research" element={<Placeholder title="Research" />} />
              <Route path="/book" element={<Placeholder title="Book" />} />
              <Route path="/decisions" element={<Placeholder title="Decisions" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
