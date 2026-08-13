import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Backtest from "./routes/Backtest";
import Glossary from "./routes/Glossary";
import Principles from "./routes/Principles";
import Strategies from "./routes/Strategies";
import Strategy from "./routes/Strategy";
import { GlossaryProvider } from "./components/GlossaryProvider";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Universe } from "./routes/Universe";
import { Company } from "./routes/Company";
import { Screener } from "./routes/Screener";
import { Research } from "./routes/Research";
import { Book } from "./routes/Book";
import { Decisions } from "./routes/Decisions";
import { ThemeProvider } from "./theme/ThemeProvider";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <GlossaryProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<Shell />}>
                <Route index element={<Universe />} />
                <Route path="/company/:ticker" element={<Company />} />
                <Route path="/screener" element={<Screener />} />
                <Route path="/research" element={<Research />} />
                <Route path="/book" element={<Book />} />
                <Route path="/decisions" element={<Decisions />} />
                <Route path="/backtest" element={<Backtest />} />
                <Route path="/glossary" element={<Glossary />} />
              <Route path="/strategies" element={<Strategies />} />
              <Route path="/strategies/:id" element={<Strategy />} />
              <Route path="/principles" element={<Principles />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </GlossaryProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
