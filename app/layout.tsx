import type { Metadata, Viewport } from "next";
import { DM_Sans } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Wolf Radar",
  description:
    "Findet reichweitenstarke deutsche Videos mit klaren Ernährungs-Falschinfos und bereitet Reaktions-Skripte vor.",
};

export const viewport: Viewport = {
  themeColor: "#141618",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="de">
      <body className={dmSans.className}>{children}</body>
    </html>
  );
}
