import { buttonVariants } from "@/components/ui/button";

export const panel = "space-y-3 rounded-lg border bg-card p-4";
export const anchor =
  "text-primary underline underline-offset-4 break-words focus-visible:outline focus-visible:outline-2";
export const destination = buttonVariants({
  variant: "outline",
  className: "h-auto min-h-11 max-w-full whitespace-normal break-words justify-start text-left focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
});
