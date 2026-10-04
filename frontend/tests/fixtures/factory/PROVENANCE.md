# Accepted P01 contract

Unmodified copies of backend/tests/factory/fixtures/v1 from artifact source eb31749bcae8f456d6df6709273afd5921d094ad; reviewed head 59c8cc9855e1a98f7d28e16abef88171c7da69ca. Schema 1. Manifest SHA256 b17dea10bb7c2f9ac2047c35f5921b9adb0dacc85b71fdc700849913471d9706. B4 independent acceptance and B3 accepted-version acknowledgment Mail357. P01 integration merge d5075ada98dd078e8d7c333acb4dd95698af79df; P02 base 423e9340da6cc93b00a3b8b576d597f70c5340fd.

The canonical first/next-page examples each contain two rows with total132. Tests explicitly derive larger page sets and empty factories from these envelopes; those cases are P02 test derivations, not additional accepted canonical scenarios. Native adapter fixtures describe implemented M1a pages only, not P03 operational readiness.

Protected retry regressions derive eligible controls from `operator_stop_retry_eligible` and synthetic legacy retry responses with `retry_requested_at`/`status_note`: deferred owner release, reset to pending, retained status, and explicit 401/409 denials. Cancellation, replacement credentials and sibling detail navigation use only stubbed requests. These are P02 test derivations against the existing protected route; canonical P01 JSON and manifest remain unchanged.

The isolated browser serves the accepted retry-eligible detail at `/work/6` and verifies a synthetic cached credential still opens the warning and Cancel sends no mutation at 360/768/1280. It rejects every non-GET request.
