import type { StatusInfo } from "../lib/clinical";
import { AlertIcon } from "./icons";

interface Props {
  status: StatusInfo;
  lastAssessed: string;
}

export default function StatusBanner({ status, lastAssessed }: Props) {
  return (
    <div className={`relative overflow-hidden rounded-2xl ${status.bg} p-5 shadow-sm`}>
      <div className={`absolute left-0 top-0 h-full w-1.5 ${status.bar}`} />
      <div className="flex items-center justify-between pl-3">
        <div className="flex items-center gap-4">
          <span className={`flex h-12 w-12 items-center justify-center rounded-xl ${status.iconBg}`}>
            <AlertIcon className="h-6 w-6" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Triage Status
            </p>
            <p className={`text-2xl font-bold ${status.text}`}>{status.label}</p>
          </div>
        </div>
        <div className="text-right text-sm">
          <p className="text-slate-500">Last assessment: {lastAssessed}</p>
          <a href="#" className={`font-semibold underline ${status.text}`}>
            View alert history
          </a>
        </div>
      </div>
    </div>
  );
}
