# GCP icon set: source and licence

## Source

Official Google Cloud icon library: <https://cloud.google.com/icons> (downloaded 2026-10-20). The page links three zips: core product icons (<https://services.google.com/fh/files/misc/core-products-icons.zip>), category icons (<https://services.google.com/fh/files/misc/category-icons.zip>) and legacy console icons (<https://services.google.com/fh/files/misc/google-cloud-legacy-icons.zip>), plus an overview PDF (<https://services.google.com/fh/files/misc/google-cloud-product-icons.pdf>).

The files in this folder are **not** Google's. They are original glyphs drawn for this skill (24x24 viewBox, a hexagon in the GCP category colour with a white symbol). They imitate the category colouring only. See Licence for why.

## Licence

The official page https://cloud.google.com/icons (fetched 2026-10-20) contains no usage or licence text, and the three zips contain no licence or readme file. The overview PDF is an image-based document in which no terms text could be extracted (not read visually). The page's only wording is: "Welcome to the official library for Google Cloud product icons. Here you can find the Google Cloud product icons you need for your diagrams, technical documentation, and more."

A copy of an older Google icon deck on SlideShare (<https://www.slideshare.net/slideshow/google-cloud-official-icons-and-solution-architecturespptx/259825728>) is reported to say the product logos may be used freely and without permission to accurately reference Google's technology and tools, for instance in books or architecture diagrams. This is secondhand (not on Google's own site) and covers a different, older icon set, so it is not relied on.

**Result: the terms are unclear about redistributing the icons in a private repository.** The fallback applies: the Google files were not copied into the repo. This folder holds drawn glyphs instead. Deviation from the brief: the brief says "one per category"; because every named product needs its own file, there is one drawn glyph per product, tinted by its category colour, plus four generic single-colour glyphs.

To swap in the official icons later, once the terms are confirmed, replace each file by the same name (the legacy zip has cloud_run, pubsub, secret_manager, virtual_private_cloud, workload_identity_pool and others; it has no Service Account icon).

## Icons

| file | product | GCP category |
|---|---|---|
| cloud-run.svg | Cloud Run | Serverless |
| cloud-functions.svg | Cloud Functions | Serverless |
| pubsub.svg | Pub/Sub | Integration services |
| bigquery.svg | BigQuery | Data analytics |
| cloud-storage.svg | Cloud Storage | Storage |
| artifact-registry.svg | Artifact Registry | Developer tools & DevOps |
| secret-manager.svg | Secret Manager | Security & identity |
| iam.svg | IAM | Security & identity |
| workload-identity-federation.svg | Workload Identity Federation | Security & identity |
| vpc.svg | VPC | Networking |
| cloud-load-balancing.svg | Cloud Load Balancing | Networking |
| cloud-build.svg | Cloud Build | Developer tools & DevOps |
| cloud-scheduler.svg | Cloud Scheduler | Integration services |
| firestore.svg | Firestore | Databases |
| cloud-sql.svg | Cloud SQL | Databases |
| cloud-monitoring.svg | Cloud Monitoring | Operations |
| cloud-logging.svg | Cloud Logging | Operations |
| service-account.svg | Service Account | Security & identity |
| gitlab.svg | GitLab | Generic |
| ci-job.svg | CI job | Generic |
| external-system.svg | External system | Generic |
| user.svg | User | Generic |
