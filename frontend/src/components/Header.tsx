import { RadarIcon, SearchIcon } from "./icons";

const NAV = ["Dashboard", "Patient List", "Analytics", "Citations", "System Logs"];

export default function Header() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-8 px-6 py-3">
        <div className="flex items-center gap-2 text-xl font-bold text-blue-700">
          <RadarIcon className="h-6 w-6" />
          ChronoSense
        </div>

        <nav className="hidden items-center gap-7 text-sm font-medium text-slate-500 md:flex">
          {NAV.map((item, i) => (
            <a
              key={item}
              href="#"
              className={
                i === 0
                  ? "border-b-2 border-blue-600 pb-3 text-slate-900"
                  : "pb-3 hover:text-slate-800"
              }
            >
              {item.toUpperCase()}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-4">
          <div className="hidden items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-400 lg:flex">
            <SearchIcon className="h-4 w-4" />
            <span>Search patients or metrics…</span>
          </div>
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-500" />
          </span>
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
              DP
            </div>
            <span className="text-sm font-semibold text-slate-700">DR. PETERSON</span>
          </div>
        </div>
      </div>
    </header>
  );
}
