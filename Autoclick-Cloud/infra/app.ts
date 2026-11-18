import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as rolesanywhere from 'aws-cdk-lib/aws-rolesanywhere';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import { HttpJwtAuthorizer, HttpIamAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const app = new cdk.App();
const localConfigPath = join(__dirname, '../cdk.local.json');
const localConfig: Record<string, unknown> = existsSync(localConfigPath)
  ? JSON.parse(readFileSync(localConfigPath, 'utf8').replace(/^\uFEFF/, '')) : {};
function setting(name: string, required = true): string {
  const value = app.node.tryGetContext(name) ?? localConfig[name];
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (!required) return '';
  throw new Error(`Falta ${name}. Completar cdk.local.json a partir de cdk.local.example.json o usar --context.`);
}
const account = setting('account');
const region = setting('region');
const poolId = setting('userPoolId');
const desktopClientId = setting('desktopClientId');
const desktopUnlimitedSub = setting('desktopUnlimitedSub', false);
const artifacts = new cdk.Stack(app, 'AutoClickArtifacts', { env: { account, region }, synthesizer: new cdk.BootstraplessSynthesizer(), terminationProtection: true });
new s3.Bucket(artifacts, 'Templates', { bucketName: `autoclick-templates-${account}-${region}`, encryption: s3.BucketEncryption.S3_MANAGED,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, enforceSSL: true, versioned: true, removalPolicy: cdk.RemovalPolicy.RETAIN });
const stack = new cdk.Stack(app, 'AutoClickControl', {
  env: { account, region }, terminationProtection: true,
  synthesizer: new cdk.BootstraplessSynthesizer(),
  description: 'AutoClick enterprise API. Web hosting remains on DonWeb.',
});
cdk.Tags.of(stack).add('Project', 'AutoClick');
cdk.Tags.of(stack).add('Environment', 'development');

// Explicit isolated subnets: no NAT Gateway, no public DB endpoint, no inbound rules.
const vpc = new ec2.Vpc(stack, 'DatabaseVpc', {
  availabilityZones: ['us-east-1a', 'us-east-1b'], natGateways: 0,
  subnetConfiguration: [{ name: 'database', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 }],
});
const group = new ec2.SecurityGroup(stack, 'DatabaseSecurity', { vpc, allowAllOutbound: false });
const subnet = new rds.CfnDBSubnetGroup(stack, 'DatabaseSubnets', {
  dbSubnetGroupDescription: 'Private AutoClick database subnets', subnetIds: vpc.isolatedSubnets.map(s => s.subnetId),
});
const maxCapacity = new cdk.CfnParameter(stack, 'DatabaseMaxCapacity', {
  type: 'Number', default: 2, minValue: 1, maxValue: 16,
  description: 'Development cost ceiling, not a measured production capacity recommendation. Review after load tests.',
});
const db = new rds.CfnDBCluster(stack, 'Database', {
  engine: 'aurora-postgresql', engineVersion: '16.8', engineMode: 'provisioned',
  databaseName: 'autoclick', masterUsername: 'autoclick_admin', manageMasterUserPassword: true,
  storageEncrypted: true, backupRetentionPeriod: 7, deletionProtection: true,
  enableHttpEndpoint: true, dbSubnetGroupName: subnet.ref, vpcSecurityGroupIds: [group.securityGroupId],
  serverlessV2ScalingConfiguration: { minCapacity: 0, maxCapacity: maxCapacity.valueAsNumber, secondsUntilAutoPause: 300 },
});
db.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);
const instance = new rds.CfnDBInstance(stack, 'DatabaseWriter', {
  engine: 'aurora-postgresql', dbClusterIdentifier: db.ref, dbInstanceClass: 'db.serverless', publiclyAccessible: false,
});
instance.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);

const pool = cognito.UserPool.fromUserPoolId(stack, 'ExistingIdentity', poolId);
const webClient = new cognito.UserPoolClient(stack, 'WebClient', {
  userPool: pool, userPoolClientName: 'autoclick-web', generateSecret: false,
  authFlows: { userSrp: true }, preventUserExistenceErrors: true, enableTokenRevocation: true,
  accessTokenValidity: cdk.Duration.hours(1), idTokenValidity: cdk.Duration.hours(1), refreshTokenValidity: cdk.Duration.days(30),
});
new cognito.CfnUserPoolGroup(stack, 'Administrators', { userPoolId: poolId, groupName: 'AUTOCLICK_ADMIN', description: 'Platform administrators; tenant roles live in the database.' });

const functionLogs = new logs.LogGroup(stack, 'FunctionLogs', { retention: logs.RetentionDays.ONE_MONTH });
const releases = new s3.Bucket(stack, 'DesktopReleases', {
  encryption: s3.BucketEncryption.S3_MANAGED, blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  enforceSSL: true, versioned: true, removalPolicy: cdk.RemovalPolicy.RETAIN,
});
const avatars = new s3.Bucket(stack, 'ProfilePhotos', {
  encryption: s3.BucketEncryption.S3_MANAGED, blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  enforceSSL: true, removalPolicy: cdk.RemovalPolicy.RETAIN,
});
const backend = new lambda.Function(stack, 'EnterpriseApi', {
  runtime: lambda.Runtime.PYTHON_3_12, handler: 'index.handler', timeout: cdk.Duration.seconds(28), memorySize: 512,
  code: lambda.Code.fromInline(readFileSync(join(__dirname, '../backend/index.py'), 'utf8')),
  logGroup: functionLogs,
  environment: { DB_CLUSTER_ARN: db.attrDbClusterArn, DB_SECRET_ARN: db.attrMasterUserSecretSecretArn,
    USER_POOL_ID: poolId, WORKER_ROLE_NAME: 'autoclick-ia-worker', AVATAR_BUCKET: avatars.bucketName,
    ...(desktopUnlimitedSub ? { DESKTOP_UNLIMITED_SUB: desktopUnlimitedSub } : {}),
    DESKTOP_RELEASE_BUCKET: releases.bucketName, DESKTOP_RELEASE_KEY: 'desktop/AutoClick-3.0-windows-x64.zip' },
});
releases.grantRead(backend, 'desktop/*');
avatars.grantRead(backend, 'avatars/*');
avatars.grantPut(backend, 'avatars/*');
avatars.grantDelete(backend, 'avatars/*');
backend.addToRolePolicy(new iam.PolicyStatement({ actions: ['cognito-idp:AdminListGroupsForUser', 'cognito-idp:AdminDeleteUser'], resources: [pool.userPoolArn] }));
new events.Rule(stack, 'RetryAccountDeletions', {
  schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
  targets: [new targets.LambdaFunction(backend, { event: events.RuleTargetInput.fromObject({ task: 'retry-account-deletions' }) })],
});
backend.addToRolePolicy(new iam.PolicyStatement({ actions: ['rds-data:ExecuteStatement', 'rds-data:BeginTransaction', 'rds-data:CommitTransaction', 'rds-data:RollbackTransaction'], resources: [db.attrDbClusterArn] }));
backend.addToRolePolicy(new iam.PolicyStatement({ actions: ['secretsmanager:GetSecretValue'], resources: [db.attrMasterUserSecretSecretArn] }));

const api = new apigw.HttpApi(stack, 'HttpApi', {
  apiName: 'autoclick-enterprise', corsPreflight: {
    allowOrigins: ['https://autoclick.website', 'https://www.autoclick.website', 'http://localhost:3000', 'http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:5180'],
    allowMethods: [apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PATCH, apigw.CorsHttpMethod.DELETE, apigw.CorsHttpMethod.OPTIONS],
    allowHeaders: ['Authorization', 'Content-Type'], maxAge: cdk.Duration.hours(1),
  },
});
const integration = new HttpLambdaIntegration('ControlIntegration', backend);
const authorizer = new HttpJwtAuthorizer('UserAccess', `https://cognito-idp.${region}.amazonaws.com/${poolId}`, {
  jwtAudience: [webClient.userPoolClientId, desktopClientId],
});
api.addRoutes({ path: '/v1/{proxy+}', methods: [apigw.HttpMethod.GET, apigw.HttpMethod.POST, apigw.HttpMethod.PATCH, apigw.HttpMethod.DELETE], integration, authorizer });
const businessRoutes = api.addRoutes({ path: '/v1/business-requests', methods: [apigw.HttpMethod.POST], integration });
for (const route of ['validate', 'complete', 'fail']) {
  api.addRoutes({ path: `/v1/ai/${route}`, methods: [apigw.HttpMethod.POST], integration, authorizer: new HttpIamAuthorizer() });
}
const accessLogs = new logs.LogGroup(stack, 'ApiLogs', { retention: logs.RetentionDays.ONE_MONTH });
const stage = api.defaultStage!.node.defaultChild as apigw.CfnStage;
stage.addDependency(businessRoutes[0].node.defaultChild as apigw.CfnRoute);
stage.defaultRouteSettings = { throttlingBurstLimit: 20, throttlingRateLimit: 5 };
stage.routeSettings = { 'POST /v1/business-requests': { ThrottlingBurstLimit: 2, ThrottlingRateLimit: 0.2 } };
stage.accessLogSettings = { destinationArn: accessLogs.logGroupArn,
  format: JSON.stringify({ requestId: '$context.requestId', route: '$context.routeKey', status: '$context.status', integrationError: '$context.integrationErrorMessage' }) };

const workerCaPath = join(__dirname, 'worker-ca.pem');
if (!existsSync(workerCaPath)) {
  throw new Error('Falta infra/worker-ca.pem: colocar el certificado publico de la CA autorizada para este despliegue.');
}
const anchor = new rolesanywhere.CfnTrustAnchor(stack, 'WorkerTrustAnchor', {
  name: 'autoclick-worker-ca', enabled: true,
  source: { sourceType: 'CERTIFICATE_BUNDLE', sourceData: { x509CertificateData: readFileSync(workerCaPath, 'utf8') } },
});
const worker = new iam.CfnRole(stack, 'WorkerIdentity', {
  roleName: 'autoclick-ia-worker', maxSessionDuration: 3600,
  assumeRolePolicyDocument: { Version: '2012-10-17', Statement: [{ Effect: 'Allow', Principal: { Service: 'rolesanywhere.amazonaws.com' },
    Action: ['sts:AssumeRole', 'sts:TagSession', 'sts:SetSourceIdentity'],
    Condition: { ArnEquals: { 'aws:SourceArn': anchor.attrTrustAnchorArn }, StringEquals: { 'aws:SourceAccount': account, 'aws:PrincipalTag/x509Subject/CN': 'autoclick-ia-worker' } } }] },
  policies: [{ policyName: 'ReportOnly', policyDocument: { Version: '2012-10-17', Statement: [{ Effect: 'Allow', Action: 'execute-api:Invoke', Resource: ['validate', 'complete', 'fail'].map(p => `arn:aws:execute-api:${region}:${account}:${api.apiId}/*/POST/v1/ai/${p}`) }] } }],
});
const workerProfile = new rolesanywhere.CfnProfile(stack, 'WorkerProfile', {
  name: 'autoclick-ia-worker', enabled: true, durationSeconds: 900, roleArns: [worker.attrArn],
});
new cdk.CfnOutput(stack, 'WorkerTrustAnchorArn', { value: anchor.attrTrustAnchorArn });
new cdk.CfnOutput(stack, 'WorkerProfileArn', { value: workerProfile.attrProfileArn });
new cloudwatch.Alarm(stack, 'ApiErrors', { metric: backend.metricErrors(), threshold: 3, evaluationPeriods: 1, treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING });
new cloudwatch.Alarm(stack, 'DatabaseCapacity', { metric: new cloudwatch.Metric({ namespace: 'AWS/RDS', metricName: 'ACUUtilization', dimensionsMap: { DBInstanceIdentifier: instance.ref }, statistic: 'Maximum' }), threshold: 90, evaluationPeriods: 3 });
new cdk.CfnOutput(stack, 'ApiUrl', { value: api.apiEndpoint });
new cdk.CfnOutput(stack, 'WebClientId', { value: webClient.userPoolClientId });
new cdk.CfnOutput(stack, 'UserPoolId', { value: poolId });
new cdk.CfnOutput(stack, 'Region', { value: region });
new cdk.CfnOutput(stack, 'FunctionName', { value: backend.functionName });
new cdk.CfnOutput(stack, 'WorkerRoleArn', { value: worker.attrArn });
new cdk.CfnOutput(stack, 'DatabaseArn', { value: db.attrDbClusterArn });
new cdk.CfnOutput(stack, 'DesktopReleaseBucket', { value: releases.bucketName });
new cdk.CfnOutput(stack, 'ProfilePhotoBucket', { value: avatars.bucketName });
app.synth();
