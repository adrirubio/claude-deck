import { buttonVariants } from "@/components/ui/button";

export const panel = "space-y-3 rounded-lg border bg-card p-4";
export const anchor =
  "text-foreground underline underline-offset-4 wrap-break-word focus-visible:outline-solid focus-visible:outline-2";
export const destination = buttonVariants({
  variant: "outline",
  className: "h-auto min-h-11 max-w-full whitespace-normal wrap-break-word justify-start text-left focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
});
