const pulumi = require("@pulumi/pulumi");
const aws = require("@pulumi/aws");

const awsAccessKey = new pulumi.Config("aws").require("accessKey");

const awsSecretKey = new pulumi.Config("aws").require("secretKey");

const awsRegion = new pulumi.Config("aws").require("region");

const awsVpcCidr = new pulumi.Config("vpc").require("cidrBlock");

const awsDevProvider = new aws.Provider("awsdev", {
  accessKey: awsAccessKey,
  secretKey: awsSecretKey,
  region: awsRegion,
});

const vpc = new aws.ec2.Vpc("vpc", {
  cidrBlock: awsVpcCidr,
  enableDnsSupport: true,
  enableDnsHostnames: true,
  tags: {
    Name: "VPC01",
  },
});

const gateway = new aws.ec2.InternetGateway("gateway", {
  vpcId: vpc.id,
  tags: {
    Name: "main_gateway",
  },
});

const availableZones = aws.getAvailabilityZones({ state: "available" });

const desiredAzCount = 3; // change 2 or 3 needed

const azs = availableZones.then((zones) =>
  zones.names.slice(0, desiredAzCount)
);

if (desiredAzCount >= 2 && desiredAzCount <= 3) {
  const publicSubnets = azs.then((azNames) =>
    azNames.map((az, i) => {
      return new aws.ec2.Subnet(`public-subnet-${i + 1}`, {
        vpcId: vpc.id,
        cidrBlock: `10.0.${i + 1}.0/24`,
        mapPublicIpOnLaunch: true,
        availabilityZone: az,
        tags: {
          Name: `public-subnet-${i + 1}`,
        },
      });
    })
  );

  const privateSubnets = azs.then((azNames) =>
    azNames.map((az, i) => {
      return new aws.ec2.Subnet(`private-subnet-${i + 1}`, {
        vpcId: vpc.id,
        cidrBlock: `10.0.${i + 6 + 1}.0/24`,
        mapPublicIpOnLaunch: false,
        availabilityZone: az,
        tags: {
          Name: `private-subnet-${i + 1}`,
        },
      });
    })
  );

  const publicRouteTable = new aws.ec2.RouteTable("public-route-table", {
    vpcId: vpc.id,
    tags: {
      Name: "Public Route Table",
    },
  });

  const privateRouteTable = new aws.ec2.RouteTable("private-route-table", {
    vpcId: vpc.id,
    tags: {
      Name: "Private Route Table",
    },
  });

  pulumi
    .all([publicSubnets, privateSubnets])
    .apply(([publicSubnets, privateSubnets]) => {
      publicSubnets.forEach((subnet, i) => {
        new aws.ec2.RouteTableAssociation(
          `public-route-table-association-${i}`,
          {
            routeTableId: publicRouteTable.id,
            subnetId: subnet.id,
          }
        );
      });

      privateSubnets.forEach((subnet, i) => {
        new aws.ec2.RouteTableAssociation(
          `private-route-table-association-${i}`,
          {
            routeTableId: privateRouteTable.id,
            subnetId: subnet.id,
          }
        );
      });

      new aws.ec2.Route("route", {
        routeTableId: publicRouteTable.id,
        destinationCidrBlock: "0.0.0.0/0",
        gatewayId: gateway.id,
      });
    });
} else {
  throw new Error("Desired number of availability zones must be 2 or 3");
}

pulumi.output("vpc_id", vpc.id);

//update 2